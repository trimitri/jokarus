#include <stdlib.h>
#include <stdio.h>
#include "libmccdaq.h"

int main() {

  puts("Opening connection...");
  OpenConnection();
  puts("Opened connection...");
  /*
  TriangleOnce(1., -10, 10);
  uint n_channels = sizeof(channels);
  uint n_samples = 600;
  double frequency = 500;

  double * data = calloc(n_samples * n_channels, sizeof(double));
  SampleChannelsAt10V(channels, n_channels, n_samples, frequency, data);
  for (uint sample = 0; sample < n_samples; sample++) {
    if (sample % 50 == 0) {
      for (uint channel = 0; channel < n_channels; channel++) {
        printf("%10g  ", (double) data[sample * n_channels + channel]);
      }
      printf("\n");
    }
  }
  free(data);
  */

  uint n_samples = LIBMCCDAQ_BULK_TRANSFER_SIZE / 2;
  const uint8_t channels[] = {11, 7, 12};
  const uint8_t gains[] = {10, 10, 10};
  const uint n_channels = 3;
  uint16_t * data = calloc(n_samples * n_channels, sizeof(uint16_t));
  puts("Fetching Scan...");
  FetchScan(
      0.,
      19.99,
      .2,
      n_samples,
      channels,
      gains,
      n_channels,
      kDescent,
      data);
  puts("Fetched Scan...");
  for (uint i = 0; i < n_samples; i++) {
    if (i % 10 == 0) {
      printf("%d\t%d\t%d\n", data[3*i], data[3*i + 1], data[3*i + 2]);
    }
  }
  free(data);

  return 0;
}
