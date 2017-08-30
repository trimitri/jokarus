#include <stdlib.h>
#include <stdio.h>
#include "libmccdaq.h"

int main() {

  OpenConnection();
  /*
  TriangleOnce(1., -10, 10);
  uint8_t channels[] = {10, 11, 12};
  uint n_channels = sizeof(channels);
  uint n_samples = 600;
  double frequency = 500;

  double * data = calloc(n_samples * n_channels, sizeof(double));
  SampleChannelsAt10V(channels, n_channels, n_samples, frequency, data);
  for (uint sample = 0; sample < n_samples; sample++) {
    for (uint channel = 0; channel < n_channels; channel++) {
      printf("%10g  ", (double) data[sample * n_channels + channel]);
    }
    printf("\n");
  }
  free(data);
  */

  uint n = 20;
  uint16_t samples[n];
  uint ret = GenerateSignal(0, n, 5, 5., 0., samples);
  if (ret == 0) {
    printf("Success!\n");
    for (uint i = 0; i < n; i++) {
      printf("%d\n", samples[i]);
    }
  } else {
    printf("Failure.\n");
  }
}
