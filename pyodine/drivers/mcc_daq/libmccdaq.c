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

static const uint kUsbTimeout = 1000;  // USB connection timout in ms.
static const uint16_t kMaxAmplitude = 65535;  // 2^16-1

static libusb_device_handle *dev = NULL;

Error FetchScan(
    const double offset,
    const double amplitude,
    const double duration,
    const uint n_samples,
    const uint8_t * channels,
    const uint8_t * gains,
    const uint n_chan,
    const SignalType type,
    uint16_t *readings) {
  const double sample_rate = n_samples / duration;

  // Generate a signal and send it to the device.

  uint16_t *signal = calloc(n_samples, sizeof(uint16_t)); 
  Error ret = GenerateSignal(type, n_samples, 100, amplitude, offset, signal);
  if (ret != 0) {
    puts("Error generating signal.");
    return ret;
  }
  ret = OutputSignal(signal, n_samples, sample_rate);
  free(signal);
  if (ret != 0) {
    puts("Error sending signal.");
    return ret;
  }

  // Output is running. Now start reading ASAP.
  ret = SampleChannels(n_samples, sample_rate, channels, gains, n_chan, readings); 
  return ret;
}

void GenerateTriangleSignal(uint length, double min, double max,
                            uint16_t *amplitudes) {
  // validation
  if (min < -10. || min > 10. || max < -10. || max > 10. || min > max) {
    min = -10.;
    max = 10.;
    puts("Invalid range for triangle signal. Defaulting to +-10V.");
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

Error GenerateSignal(enum SignalType signal, uint n_samples,
    uint n_prefix, double amplitude, double offset, uint16_t *samples) {
  if (n_samples > LIBMCCDAQ_BULK_TRANSFER_SIZE) {
    puts("Won't generate more samples than the DAQ can take");
    return kValueError;
  }
  if (n_prefix > n_samples) {
    puts("Must not have more prefix than total samples.");
    return kValueError;
  }
  if (amplitude < 0. || amplitude > 20.) {
    puts("Total amplitude must not exceed 20 Volts");
    return kValueError;
  }
  if (offset < -10 || offset > 10
      || offset + amplitude / 2 > 10 || offset - amplitude / 2 < -10) {
    puts("Combination of offset and amplitude must not exceed +/- 10 volts.");
    return kValueError;
  }
  uint n_signal_samples = n_samples - n_prefix - 1; 
  uint16_t zero = VoltsToCounts(offset);
  uint16_t min =  VoltsToCounts(offset - amplitude / 2.);
  uint16_t max =  VoltsToCounts(offset + amplitude / 2.);

  // Prefix zero padding.
  for (uint i = 0; i < n_prefix; i++) {
    samples[i] = zero;
  }

  // Actual signal.
  switch (signal) {
    case kDescent:
      IntegerSlope(max, min, n_signal_samples, samples + n_prefix);
      break;
    case kAscent:
      IntegerSlope(min, max, n_signal_samples, samples + n_prefix);
      break;
    case kDip:
      return kNotImplementedError;
  }
  // The DAQ output voltage will always stay at the last value, thus we return
  // to "zero" here.
  samples[n_samples - 1] = zero;

  return kSuccess;
}

Error OpenConnection(void) {

  // Initialize libusb.
  int ret = libusb_init(NULL);
  if (ret < 0) {
    puts("Failed to initialize libusb");
    return kOSError;
  }

  // Initialize USB connection.
  if ((dev = usb_device_find_USB_MCC(USB1608GX_2AO_PID, NULL))) {
    usbInit_1608G(dev, 1);
    return kSuccess;
  } else {
    puts("Failure, did not find a USB 1608G series device!");
    return kConnectionError;
  }
}

Error OutputSignal(uint16_t *samples, uint n_samples, double sample_rate) {
  if (2 * n_samples > LIBMCCDAQ_BULK_TRANSFER_SIZE) {
    puts("Too much data to send it at once.");
    return kValueError; 
  }
  if (!(sample_rate > 0.)) {
    puts("Provide sample rate in Hz.");
    return kValueError;
  }

  usbAOutScanStop_USB1608GX_2AO(dev);  // Stop any prev. running scan.

  // The device has an internal FIFO queue storing the values to be put out
  // during an analog output scan. The output scan will start immediately after
  // the ScanStart command is issued if and only if we "primed" the FIFO buffer
  // first.
  // To do this, we first make sure that the buffer is empty and then store a
  // single period of data in it. This usually buys us enougth time to start
  // filling up the FIFO after the scan started.
  usbAOutScanClearFIFO_USB1608GX_2AO(dev);

  // The samples for the 16-bit output stage are 2-byte unsigned integers. As
  // the USB transfer only accepts single bytes ("char"), we send double the
  // amount of bytes as we have samples.
  int n_transferred_bytes;
  int ret = libusb_bulk_transfer(dev, LIBUSB_ENDPOINT_OUT|2,
      (unsigned char *) samples, 2 * (int) n_samples,
      &n_transferred_bytes, kUsbTimeout);
  if (2 * (int) n_samples != n_transferred_bytes || ret != 0) {
    puts("Error transferring data to device.");
    return kConnectionError;
  }
  usbAOutScanStart_USB1608GX_2AO(dev,
      // total # of samples to produce before stopping scan automatically
      n_samples,
      0,            // only relevant if using retrigger mode
      sample_rate,  // sample rate, see comments in usb-1608G.c for details
      AO_CHAN0);

  // If we stopped the scan here, the device would cease processing it's FIFO
  // queue (see above) immediately and not be able to output even a single
  // period.  But as we provided the exact number of desired samples in the
  // StartScan command, we don't need to explicitly stop the scan at all.
  return kSuccess;
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

Error SampleChannels(
    const uint n_samples,
    const double frequency,
    const uint8_t *channels,
    const uint8_t gains[],
    const uint n_channels,
    uint16_t * results) {

  usbAInScanStop_USB1608G(dev);
  usbAInScanClearFIFO_USB1608G(dev);

  // Create a channel configuration for the analog input scan and save it to the
  // device.
  ScanList list[n_channels];
  // As gain settings are defined as hex values in usb-1608G.h, we need this
  // bulky translator here:
  for (uint i = 0; i < n_channels; i++) {
    uint8_t gain = BP_10V;
    switch (gains[i]) {
      case 1:
        gain = BP_1V;
        break;
      case 2:
        gain = BP_2V;
        break;
      case 5:
        gain = BP_5V;
      // Default is 10V (see above)
    }
    list[i].channel = channels[i];
    list[i].mode = SINGLE_ENDED;
    list[i].range = gain;
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
    results[i] = rcv_data[i];
  }
  free(rcv_data);
  return kSuccess;
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

uint16_t VoltsToCounts(double volts) {
  // We round by adding .5 and then truncating to zero.
  return (uint16_t) ((kMaxAmplitude * (volts + 10.) / 20.) + .5);
}

Error IntegerSlope(uint16_t start, uint16_t stop, uint n_samples,
                   uint16_t *samples) {
  for (uint i = 0; i < n_samples; i ++) {
    double exact = start + (stop - start) * (double) i / (n_samples - 1);
    samples[i] = (uint16_t) (exact + .5);
    /* if (i % 50 == 0) printf("%d\n", samples[i]); */
  }
  return kSuccess;
}
