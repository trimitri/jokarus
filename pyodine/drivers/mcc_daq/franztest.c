#include <stdlib.h>
#include <stdio.h>
#include "libmccdaq.h"

int main() {

  OpenConnection();
  /*
  TriangleOnce(1., -10, 10);
  uint8_t channels[] = {7, 12, 13};
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
  uint n_channels = 2;
  double * data = calloc(n_samples * n_channels, sizeof(double));
  FetchScan(0., 19.99, .05, kDescent, data);
  for (uint i = 0; i < n_samples; i++) {
    if (i % 3 == 0) {
      printf("%g\t%g\n", data[2*i], data[2*i + 1]);
    }
  }
  free(data);
}
