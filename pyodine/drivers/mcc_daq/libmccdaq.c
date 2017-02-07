#include <stdio.h>
#include <stdlib.h>
#include <ctype.h>
#include <math.h>
#include <fcntl.h>
#include <unistd.h>

#include "pmd.h"
#include "usb-1608G.h"
#include "libmccdaq.h"

// Max. count of 2-byte integers for an USB bulk transfer the bus can tolerate.
#define LIBMCCDAQ_BULK_TRANSFER_SIZE 2560

static const uint kUsbTimeout = 1000;  // USB connection timout in ms.
static const uint16_t kMaxAmplitude = 65535;  // 2^16-1

// Period time of generated signal in seconds.
static const double kRampDuration = 2.0;

static libusb_device_handle *dev = NULL;

// Configure the analog input channels to use single-ended detection and full
// range.
static void InitDevice() {

  // Build an options set.
  ScanList channel_conf[16];
  for (uint8_t channel = 0; channel < 16; channel++) {
    channel_conf[channel].mode = SINGLE_ENDED;
    channel_conf[channel].range = BP_10V;
    channel_conf[channel].channel = channel;
  }

  // Send it to the device.
  usbAInConfig_USB1608G(dev, channel_conf);
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

  InitDevice();

  return dev;
}


void Triangle() {

  // holds 16 bit unsigned analog output data
  uint16_t ramp[LIBMCCDAQ_BULK_TRANSFER_SIZE];
  GenerateTriangleSignal(LIBMCCDAQ_BULK_TRANSFER_SIZE, ramp);
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

void TriangleOnce() {
  uint16_t amplitudes[LIBMCCDAQ_BULK_TRANSFER_SIZE];
  GenerateTriangleSignal(LIBMCCDAQ_BULK_TRANSFER_SIZE, amplitudes);

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
  ret = libusb_bulk_transfer(dev, LIBUSB_ENDPOINT_OUT|2,
      (unsigned char *) amplitudes, sizeof(amplitudes),
      &transferred_byte_ct, kUsbTimeout);
  printf("transferred: %d, ret: %d\n", transferred_byte_ct, ret);

  double rate = LIBMCCDAQ_BULK_TRANSFER_SIZE * 1./kRampDuration;
  printf("rate: %f\n", rate);
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

float * SampleChannels(uint8_t channels[], uint n_channels, uint n_samples, double frequency,
                    uint8_t gains[]) {

  usbAInScanStop_USB1608G(dev);
  usbAInScanClearFIFO_USB1608G(dev);

  // All those three lines are necessare to prepare the device for analog input
  // scanning.
  ScanList list[n_channels];
  for (uint i = 0; i < n_channels; i++) {
    list[i].channel = channels[i];
    list[i].mode = SINGLE_ENDED;
    list[i].range = gains[i];
  }
  list[n_channels-1].mode |= LAST_CHANNEL;
  usbAInConfig_USB1608G(dev, list);

  uint16_t *rcv_data;
  if ((rcv_data = calloc(n_channels*n_samples, 2)) == NULL) {
    perror("Can not allocate memory for analog input scanning.");
  }
  usbAInScanStart_USB1608G(dev, n_samples, 0, frequency, 0x0);
  int ret = usbAInScanRead_USB1608G(dev, n_samples, n_channels, rcv_data, 20000);
  printf("Number bytes read = %d  (should be %d)\n", ret, 2*n_channels*n_samples);

  float * voltages = malloc(n_samples * n_channels * sizeof(float));

  for (uint i = 0; i < n_samples; i++) {
    for (uint j = 0; j < n_channels; j++) {
      uint k = i*n_channels + j;
      voltages[k] = (float) rcv_data[k] / (kMaxAmplitude) * 20. - 10.;
      /* voltages[k] = (float) rcv_data[k]; */
    }
  }
  free(rcv_data);
  return voltages;
}

float * SampleChannelsAt10V(uint8_t channels[], uint n_channels,
    uint n_samples, double freq) {
  uint8_t gains[n_channels];
  for (uint i = 0; i < n_channels; i++) {
    gains[i] = BP_10V;
  }
  return SampleChannels(channels, n_channels, n_samples, freq, gains);
}

void GenerateTriangleSignal(uint length, uint16_t *amplitudes) {

  // We will generate a V-shaped pulse in two steps.

  // The sweep-down part, from second-highest amplitude to zero.
  for (uint i = 0; i < length/2; i ++) {
    double amplitude = (double) kMaxAmplitude
                       * (1 - (i + 1)/(length/2.0));  // 2.0 needed!
    amplitudes[i] = (uint16_t) amplitude;
  }

  // The sweep-up part goes back from zero to max amplitude.
  for (uint i = 0; i < length/2; i ++) {
    double amplitude = (double) kMaxAmplitude * (i + 1)/(length/2);
    amplitudes[length/2 + i] = (uint16_t) amplitude;
  }
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
