#include <stdio.h>
#include <stdlib.h>
#include <ctype.h>
#include <math.h>
#include <fcntl.h>

#include "pmd.h"
#include "usb-1608G.h"
#include "libmccdaq.h"

static const uint kUsbTimeout = 1000;  // USB connection timout in ms.

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

void Sawtooth(libusb_device_handle *device) {

  unsigned int i;
  double amplitude;
  uint16_t ramp[1024]; // holds 16 bit unsigned analog output data
  static const uint ramp_length = sizeof(ramp)/sizeof(uint16_t);
  printf("ramp_length: %d\n", ramp_length);

  static const unsigned int kMaxAmplitude = 65535;  // 2^16-1

  for (i = 0; i < ramp_length; i ++) {

    // Calculate the desired amplitudes; [0, kMaxAmplitude]
    amplitude = (double) kMaxAmplitude / (ramp_length-1) * i;

    ramp[i] = (uint16_t) amplitude;
  }
  usbAOutScanStop_USB1608GX_2AO(device);

  double frequency = (double) ramp_length * 500;
  usbAOutScanStart_USB1608GX_2AO(device, 0, 0, frequency,  AO_CHAN0);
  int flag = fcntl(fileno(stdin), F_GETFL);
  fcntl(0, F_SETFL, flag | O_NONBLOCK);
  int transferred, ret;
  unsigned long int iteration_ctr = 0;
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
  usbAOutScanStop_USB1608GX_2AO(device);
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
