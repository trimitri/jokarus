#include <stdio.h>
#include <stdlib.h>
#include <ctype.h>
#include <math.h>
#include <fcntl.h>

#include "pmd.h"
#include "usb-1608G.h"

int main() {

  static const uint kUsbTimeout = 1000;  // USB connection timout in ms.

  // Initialize libusb.
  int ret = libusb_init(NULL);
  if (ret < 0) {
    perror("libusb_init: Failed to initialize libusb");
    exit(1);
  }

  // Initialize USB connection.
  libusb_device_handle *device = NULL;
  device = NULL;
  if ((device = usb_device_find_USB_MCC(USB1608GX_2AO_PID, NULL))) {
    usbInit_1608G(device, 1);
  } else {
    printf("Failure, did not find a USB 1608G series device!\n");
    return 0;
  }

  // Build a lookup table of voltages vs. values based on previous calibration.
  float table_AIN[NGAINS_1608G][2];
  usbBuildGainTable_USB1608G(device, table_AIN);
  float table_AO[NCHAN_AO_1608GX][2];
  usbBuildGainTable_USB1608GX_2AO(device, table_AO);

  // Try some signal generation.
  int channel = 0;  // Device has two output channels.

  unsigned int i;
  double voltage;
  uint16_t ramp[1024]; // holds 16 bit unsigned analog output data
  static const uint ramp_length = sizeof(ramp)/sizeof(uint16_t);
  printf("ramp_length: %d\n", ramp_length);

  static const unsigned int kMaxAmplitude = 65535;  // 2^16-1

  for (i = 0; i < ramp_length; i ++) {

    // Calculate the desired amplitudes; [0, kMaxAmplitude]
    voltage = (double) kMaxAmplitude / (ramp_length-1) * i;

    // Apply calibration data.
    ramp[i] = (uint16_t)
      ((float) voltage * table_AO[channel][0] + table_AO[channel][1]);
    /* printf("foo%d: %f\n", i, voltage); */
  }
  usbAOutScanStop_USB1608GX_2AO(device);

  double frequency = (double) ramp_length * 500;
  usbAOutScanStart_USB1608GX_2AO(device, 0, 0, frequency,  AO_CHAN0);
  int flag = fcntl(fileno(stdin), F_GETFL);
  fcntl(0, F_SETFL, flag | O_NONBLOCK);
  int transferred;
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
