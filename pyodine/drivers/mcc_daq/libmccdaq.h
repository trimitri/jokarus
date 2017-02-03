#ifndef LIBMCCDAQ_H
#define LIBMCCDAQ_H

#include <libusb-1.0/libusb.h>
#include "usb-1608G.h"

libusb_device_handle * OpenConnection(void);

void Sawtooth(libusb_device_handle *device);
void TriangleOnce(libusb_device_handle *device);
static void GenerateTriangleSignal(uint length, uint16_t *amplitudes);

void GenerateCalibrationTable(libusb_device_handle *device,
    float input_calibration[NGAINS_1608G][2],
    float output_calibration[NCHAN_AO_1608GX][2]);

#endif
