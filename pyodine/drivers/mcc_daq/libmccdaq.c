#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <math.h>
#include <fcntl.h>
#include <unistd.h>

#include "pmd.h"
#include "usb-1608G.h"
#include "libmccdaq.h"

// Max. count of 2-byte integers, USB bulk transfer can tolerate 5120 bytes.
#define LIBMCCDAQ_BULK_TRANSFER_SIZE 2560

static const uint kUsbTimeout = 1000;  // USB connection timout in ms.
static const uint16_t kMaxAmplitude = 65535;  // 2^16-1

static libusb_device_handle *dev = NULL;

enum kLogLevel {kDebug, kInfo, kWarning, kError, kCritical};

static void Log(enum kLogLevel level, char *message) {
  char *level_names[] = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"};

  char *output = calloc(strlen(message) + 30, 1);  // make room for prefix
  strcpy(output, level_names[level]);
  strcat(output, ": libmccdaq: ");
  strcat(output, message);
  strcat(output, "\n");
  fprintf(stderr, "%s", output);
  free(output);
}

libusb_device_handle * OpenConnection(void) {

  // Initialize libusb.
  int ret = libusb_init(NULL);
  if (ret < 0) {
    perror("libusb_init: Failed to initialize libusb");
    exit(1);
  }

  // Initialize USB connection.
  if ((dev = usb_device_find_USB_MCC(USB1608GX_2AO_PID, NULL))) {
    usbInit_1608G(dev, 1);
  } else {
    printf("Failure, did not find a USB 1608G series device!\n");
  }
  return dev;
}

void Triangle() {

  // holds 16 bit unsigned analog output data
  uint16_t ramp[LIBMCCDAQ_BULK_TRANSFER_SIZE];
  GenerateTriangleSignal(LIBMCCDAQ_BULK_TRANSFER_SIZE, -10., 10., ramp);
  usbAOutScanStop_USB1608GX_2AO(dev);  // Stop any prev. running scan.

  double frequency = 3.333333333 * LIBMCCDAQ_BULK_TRANSFER_SIZE;
  usbAOutScanStart_USB1608GX_2AO(dev,
      0,  // total # of scans to perform -> 0: continuous mode
      0,  // # of scans per trigger in retrigger mode
      frequency,  // repetition rate, see comments in usb-1608G.c for details
      AO_CHAN0);
  int flag = fcntl(fileno(stdin), F_GETFL);
  fcntl(0, F_SETFL, flag | O_NONBLOCK);
  int transferred, ret;
  unsigned long int iteration_ctr = 0;

  // Send the same set of data points over and over again.
  do {
    ret = libusb_bulk_transfer(dev, LIBUSB_ENDPOINT_OUT|2,
                               (unsigned char *) ramp, sizeof(ramp),
                               &transferred, kUsbTimeout);
    iteration_ctr++;
    if (ret != 0) {
      printf("USB error after %lu iterations.\n", iteration_ctr);
      break;
    }
  } while (!isalpha(getchar()));
  fcntl(fileno(stdin), F_SETFL, flag);

  // As we started the scan in continuous mode, we need to manually stop it.
  usbAOutScanStop_USB1608GX_2AO(dev);
}

void TriangleOnce(double duration, double min_ampl, double max_ampl) {

  fprintf(stdout, "min: %f, max: %f, duration: %f\n", min_ampl, max_ampl, duration);
  usbAOutScanStop_USB1608GX_2AO(dev);  // Stop any prev. running scan.

  // The device has an internal FIFO queue storing the values to be put out
  // during an analog output scan. The output scan will start immediately after
  // the ScanStart command is issued if and only if we "primed" the FIFO buffer
  // first.
  // To do this, we first make sure that the buffer is empty and then store a
  // single period of data in it. This usually buys us enougth time to start
  // filling up the FIFO after the scan started.
  usbAOutScanClearFIFO_USB1608GX_2AO(dev);
  int transferred_byte_ct, ret;

  uint16_t amplitudes[LIBMCCDAQ_BULK_TRANSFER_SIZE];
  GenerateTriangleSignal(LIBMCCDAQ_BULK_TRANSFER_SIZE, min_ampl, max_ampl,
                         amplitudes);
  ret = libusb_bulk_transfer(dev, LIBUSB_ENDPOINT_OUT|2,
      (unsigned char *) amplitudes, sizeof(amplitudes),
      &transferred_byte_ct, kUsbTimeout);
  /* printf("transferred: %d, ret: %d\n", transferred_byte_ct, ret); */

  double rate = LIBMCCDAQ_BULK_TRANSFER_SIZE * 1/duration;
  /* printf("rate: %f\n", rate); */
  usbAOutScanStart_USB1608GX_2AO(dev,
      // total # of samples to produce before stopping scan automatically
      LIBMCCDAQ_BULK_TRANSFER_SIZE,
      0,     // only relevant if using retrigger mode
      rate,  // sample rate, see comments in usb-1608G.c for details
      AO_CHAN1);

  // If we stopped the scan here, the device would cease processing it's
  // FIFO queue (see above) immediately and not be able to output even a single
  // period.  But as we provided the exact number of desired samples in the
  // StartScan command, we don't need to explicitly stop the scan at all.



}

void SampleChannels(uint8_t *channels, uint n_channels, uint n_samples, double frequency,
                    uint8_t gains[], double * results) {

  usbAInScanStop_USB1608G(dev);
  usbAInScanClearFIFO_USB1608G(dev);

  // Create a channel configuration for the analog input scan and save it to the
  // device.
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wvla"
  ScanList list[n_channels];
#pragma clang diagnostic pop
  for (uint i = 0; i < n_channels; i++) {
    list[i].channel = channels[i];
    list[i].mode = SINGLE_ENDED;
    list[i].range = gains[i];
  }
  list[n_channels-1].mode |= LAST_CHANNEL;
  usbAInConfig_USB1608G(dev, list);

  // Receive data from the device.
  usbAInScanStart_USB1608G(dev, n_samples, 0, frequency, 0x0);
  uint16_t *rcv_data = calloc(n_channels*n_samples, 2);
  int ret = usbAInScanRead_USB1608G(dev, (int) n_samples, (int) n_channels,
                                    rcv_data, 20000, 0);

  // Return error if USB connection failed.
  if (ret != (int) (sizeof(uint16_t) * n_channels * n_samples)) {
    fprintf(stderr,
            "Error (SampleChannels): Number bytes read = %d  (should be %d)\n",
            ret,
            2 * n_channels * n_samples);
  }

  // Convert to voltages and return them.
  for (uint i = 0; i < n_channels * n_samples; i++) {
    results[i] = (double) rcv_data[i] / (kMaxAmplitude) * 20. - 10.;
  }
  free(rcv_data);
}

void SampleChannelsAt10V(uint8_t *channels, uint n_channels,
    uint n_samples, double freq, double * results) {
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wvla"
  uint8_t gains[n_channels];
#pragma clang diagnostic pop
  for (uint i = 0; i < n_channels; i++) {
    gains[i] = BP_10V;
  }
  SampleChannels(channels, n_channels, n_samples, freq, gains, results);
}

void GenerateTriangleSignal(uint length, double min, double max,
                            uint16_t *amplitudes) {
  // validation
  if (min < -10. || min > 10. || max < -10. || max > 10. || min > max) {
    min = -10.;
    max = 10.;
    Log(kWarning, "Invalid range for triangle signal. Defaulting to +-10V.");
  }

  // Generate inverse triangle signal, starting and ending with max.
  double span = max - min;
  double rel_span = span / 20.;
  double offset = (min + 10) / 20.;
  for (uint i = 0; i < length; i ++) {

    // Calculate relative amplitude, max range being 0 to 1.
    double rel_ampl = fabs((double) i/(length - 1) - .5) * 2 * rel_span;

    // For accurate results we are rounding here, which is why .5 got added
    // before truncating towards zero through a cast.
    amplitudes[i] = (uint16_t) (kMaxAmplitude * (rel_ampl + offset) + .5);
  }
}

enum Error GenerateSignal(enum SignalType signal, uint n_samples,
    uint n_prefix, double amplitude, double offset, uint16_t *samples) {
  if (n_samples > LIBMCCDAQ_BULK_TRANSFER_SIZE || n_prefix > n_samples
      || amplitude < 0. || amplitude > 10.
      || offset < -10. || offset > 10.
      || offset + amplitude > 10. || offset - amplitude < -10) {
    return kValueError;
  }
  uint n_signal_samples = n_samples - n_prefix - 1; 
  uint16_t zero = (uint16_t) (kMaxAmplitude * ((offset + 10.) / 20.) + .5);
  uint16_t max =  (uint16_t) (kMaxAmplitude * ((offset + 10.) / 20.) + .5);
  return kSuccess;
}

void GenerateCalibrationTable(float input_calibration[NGAINS_1608G][2],
                              float output_calibration[NCHAN_AO_1608GX][2]) {

  // Build a lookup table of voltages vs. values based on previous calibration.
  float table_AIN[NGAINS_1608G][2];
  usbBuildGainTable_USB1608G(dev, table_AIN);
  input_calibration = table_AIN;  // return filled table

  float table_AO[NCHAN_AO_1608GX][2];
  usbBuildGainTable_USB1608GX_2AO(dev, table_AO);
  output_calibration = table_AO;  // return filled table
}

int Ping() {
  uint8_t requesttype = (DEVICE_TO_HOST | VENDOR_TYPE | DEVICE_RECIPIENT);
  uint16_t status = 0x0;

  libusb_control_transfer(dev, requesttype, 0x40, 0x0, 0x0,
                          (unsigned char *) &status, sizeof(status), 2000);
  if (status == 0x160) {
    return 0;
  }
  return 1;
}

int TestFunc(double * result) {
  static int iteration_ctr;
  iteration_ctr++;
  for (uint i = 0; i<32; i++) {
    result[i] = (double) i;
  }
  return iteration_ctr;
}
