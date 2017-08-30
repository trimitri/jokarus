#ifndef LIBMCCDAQ_H
#define LIBMCCDAQ_H

#include <libusb-1.0/libusb.h>
#include "usb-1608G.h"


libusb_device_handle * OpenConnection(void);

// Generate continuous triangle signal using full 20 volt range.
void Triangle(void);

// Generate one triangle signal, starting with the down-slope.
void TriangleOnce(double duration, double min_ampl, double max_ampl);

// Fills the array in amplitudes with a V-Shaped int series, starting with the
// second-highest value, down to zero, ending with the highest value (2^16-1).
void GenerateTriangleSignal(uint length, double min_volts, double max_volts,
                            uint16_t *amplitudes);

// Sample one or more analog outputs for the given number of samples at the
// given frequency.
void SampleChannels(uint8_t *channels, uint channel_count,
    uint sample_count, double frequency, uint8_t gains[], double * results);

// This overloads the standard definition of SampleChannels() with a variant using
// the maximum possible input gain.
void SampleChannelsAt10V(uint8_t *channels, uint channel_count,
    uint sample_count, double frequency, double * results);

int TestFunc(double * result);

void GenerateCalibrationTable(float input_calibration[NGAINS_1608G][2],
                              float output_calibration[NCHAN_AO_1608GX][2]);

// 0: The DAQ connection is alive and DAQ seems healthy
// 1: Something is wrong. Reset is advised.
//
// This internally checks the "USB Status" of the device to be 0x160, which
// seems to be "normal mode".
int Ping(void);

#endif
