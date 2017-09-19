#ifndef LIBMCCDAQ_H
#define LIBMCCDAQ_H

#include <libusb-1.0/libusb.h>
#include "usb-1608G.h"

// Max. count of bytes USB bulk transfer can tolerate. This is a hard limit and
// not only limited by USB wiring SNR.
#define LIBMCCDAQ_BULK_TRANSFER_SIZE 5120


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
Error FetchScan(
    const double offset,
    const double amplitude,
    const double duration,
    const uint n_samples,
    const uint8_t * channels,
    const uint8_t * gains,
    const uint n_chan,
    const SignalType type,
    uint16_t *readings);

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
Error SampleChannels(
    const uint n_samples,
    const double frequency,
    const uint8_t *channels,
    const uint8_t gains[],
    const uint n_channels,
    uint16_t * results);

// Generate continuous triangle signal using full 20 volt range.
void Triangle(void);

// Convert the given voltage to a digital value in "levels" alias "LSB" alias
// "counts". This will always work and does not check for legal values!
uint16_t VoltsToCounts(double volts);

#endif
