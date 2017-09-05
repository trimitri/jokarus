#ifndef LIBMCCDAQ_H
#define LIBMCCDAQ_H

#include <libusb-1.0/libusb.h>
#include "usb-1608G.h"

// Max. count of 2-byte integers, USB bulk transfer can tolerate 5120 bytes.
#define LIBMCCDAQ_BULK_TRANSFER_SIZE 2560


// "Descent" is a linear ramp from max to min, "Ascent" from min to max and
// "Dip" is a descent followed by an ascent.
typedef enum SignalType {kDescent = 1, kAscent = 2, kDip = 3} SignalType;

typedef enum Error {
    kSuccess = 0,
    kConnectionError = 1,     // connection to an external device failed
    kValueError = 2,          // function argument out of bounds or illegal
    kTypeError = 3,           // wrong argument type
    kNotImplementedError = 4,
    kOSError = 5              // error loading a library or using a system call
} Error;

// Generate a signal and read input channels while it is produced.
Error FetchScan(double offset, double amplitude, double duration,
                SignalType type, double *readings);

void GenerateCalibrationTable(float input_calibration[NGAINS_1608G][2],
                              float output_calibration[NCHAN_AO_1608GX][2]);

// Generate a signal for analog output. It will span from zero to 2^16-1.
Error GenerateSignal(enum SignalType signal, uint n_samples, uint n_prefix,
                          double amplitude, double offset, uint16_t *samples);

// Fills the array in amplitudes with a V-Shaped int series, starting with the
// second-highest value, down to zero, ending with the highest value (2^16-1).
void GenerateTriangleSignal(uint length, double min_volts, double max_volts,
                            uint16_t *amplitudes);

// Fill `n_samples` uint16_t's into the passed array `samples`. The first value
// is `start`, the last value is `stop` and in between we approximate a linear
// slope as good as possible.
Error IntegerSlope(uint16_t start, uint16_t stop, uint n_samples,
                   uint16_t *samples);

Error OpenConnection(void);

// Generate an actual signal at the device output port.
Error OutputSignal(uint16_t *samples, uint n_samples, double sample_rate);

// 0: The DAQ connection is alive and DAQ seems healthy
// 1: Something is wrong. Reset is advised.
//
// This internally checks the "USB Status" of the device to be 0x160, which
// seems to be "normal mode".
int Ping(void);

// Sample one or more analog outputs for the given number of samples at the
// given frequency.
Error SampleChannels(uint8_t *channels, uint channel_count,
    uint sample_count, double frequency, uint8_t gains[], double * results);

// This overloads the standard definition of SampleChannels() with a variant using
// the maximum possible input gain.
Error SampleChannelsAt10V(uint8_t *channels, uint channel_count,
    uint sample_count, double frequency, double * results);

// Generate continuous triangle signal using full 20 volt range.
void Triangle(void);

// Generate one triangle signal, starting with the down-slope.
void TriangleOnce(double duration, double min_ampl, double max_ampl);

// Convert the given voltage to a digital value in "levels" alias "LSB" alias
// "counts". This will always work and does not check for legal values!
uint16_t VoltsToCounts(double volts);

#endif
