#ifndef LIBMCCDAQ_H
#define LIBMCCDAQ_H

#include <libusb-1.0/libusb.h>

libusb_device_handle * OpenConnection(void);

void Sawtooth(libusb_device_handle *device);

#endif
