#include <stdio.h>
#include <stdlib.h>
#include <ctype.h>
#include <math.h>
#include <fcntl.h>

#include "pmd.h"
#include "usb-1608G.h"
#include "libmccdaq.h"

// Max. size (length of int array) of USB bulk transfers the bus can tolerate
// without stuttering.
#define LIBMCCDAQ_BULK_TRANSFER_SIZE 1024

static const uint kUsbTimeout = 1000;  // USB connection timout in ms.
static const uint16_t kMaxAmplitude = 65535;  // 2^16-1

// Period time of generated signal in seconds.
static const double kRampDuration = 3e-3;

libusb_device_handle * OpenConnection(void) {

  // Initialize libusb.
  int ret = libusb_init(NULL);
  if (ret < 0) {
    perror("libusb_init: Failed to initialize libusb");
    exit(1);
  }

  // Initialize USB connection.
  libusb_device_handle *device = NULL;

  if ((device = usb_device_find_USB_MCC(USB1608GX_2AO_PID, NULL))) {
    usbInit_1608G(device, 1);
  } else {
    printf("Failure, did not find a USB 1608G series device!\n");
  }

  return device;
}

void Triangle(libusb_device_handle *device) {

  // holds 16 bit unsigned analog output data
  uint16_t ramp[LIBMCCDAQ_BULK_TRANSFER_SIZE];
  GenerateTriangleSignal(LIBMCCDAQ_BULK_TRANSFER_SIZE, ramp);
  usbAOutScanStop_USB1608GX_2AO(device);  // Stop any prev. running scan.

  double frequency = 333.3333333 * LIBMCCDAQ_BULK_TRANSFER_SIZE;
  usbAOutScanStart_USB1608GX_2AO(device,
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
    ret = libusb_bulk_transfer(device, LIBUSB_ENDPOINT_OUT|2,
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
  usbAOutScanStop_USB1608GX_2AO(device);
}

void TriangleOnce(libusb_device_handle *device) {
  uint16_t amplitudes[LIBMCCDAQ_BULK_TRANSFER_SIZE];
  GenerateTriangleSignal(LIBMCCDAQ_BULK_TRANSFER_SIZE, amplitudes);

  usbAOutScanStop_USB1608GX_2AO(device);  // Stop any prev. running scan.
  double rate = LIBMCCDAQ_BULK_TRANSFER_SIZE * 1./kRampDuration;
  printf("rate: %f\n", rate);

  usbAOutScanStart_USB1608GX_2AO(device,
      0,  // total # of scans to perform -> 0: continuous mode
      0,  // # of scans per trigger in retrigger mode
      rate,  // repetition rate, see comments in usb-1608G.c for details
      AO_CHAN0);
  int transferred_byte_ct;
  for (uint i = 0; i < 10; i++) {
    int ret = libusb_bulk_transfer(device, LIBUSB_ENDPOINT_OUT|2,
        (unsigned char *) amplitudes, sizeof(amplitudes),
        &transferred_byte_ct, kUsbTimeout);
    printf("transferred: %d, ret: %d\n", transferred_byte_ct, ret);
  }
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

void GenerateCalibrationTable(libusb_device_handle *device,
    float input_calibration[NGAINS_1608G][2],
    float output_calibration[NCHAN_AO_1608GX][2]) {

  // Build a lookup table of voltages vs. values based on previous calibration.
  float table_AIN[NGAINS_1608G][2];
  usbBuildGainTable_USB1608G(device, table_AIN);
  input_calibration = table_AIN;  // return filled table

  float table_AO[NCHAN_AO_1608GX][2];
  usbBuildGainTable_USB1608GX_2AO(device, table_AO);
  output_calibration = table_AO;  // return filled table
}
