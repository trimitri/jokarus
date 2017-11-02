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

  uint n_samples = LIBMCCDAQ_BULK_TRANSFER_SIZE / 2;
  const uint8_t channels[] = {11, 7, 12};
  const uint8_t gains[] = {10, 2, 5};
  const uint n_channels = 3;
  uint16_t * data = calloc(n_samples * n_channels, sizeof(uint16_t));
  puts("Fetching Scan...");
  int ret = FetchScan(
      0.,
      19.99,
      .2,
      n_samples,
      channels,
      gains,
      n_channels,
      kDescent,
      data);
  if (ret != 0) {
    puts("ey!");
  } else {
    puts("Fetched Scan...");
    for (uint i = 0; i < n_samples; i++) {
      if (i % 100 == 0) {
        printf("%d\t%d\t%d\n", data[3*i], data[3*i + 1], data[3*i + 2]);
      }
    }
  }
  free(data);
  char str[12];
  sprintf(str, "%d", Ping());
  puts(str);
  */
  puts("Reading Temps...");
  uint16_t * readings = calloc(5 * 4, sizeof(uint16_t));
  const uint8_t chans[] = {0, 3, 8, 4};
  const uint8_t gns[] = {5, 5, 5, 5};
  int ret = SampleChannels(10, 100., chans, gns, 4, readings);
  if (ret != 0) {
    puts("ey!");
  } else {
    puts("Fetched Scan...");
    for (uint i = 0; i < 10; i++) {
      printf("%d\t%d\t%d\t%d\n",
             readings[4*i],
             readings[4*i + 1],
             readings[4*i + 2],
             readings[4*i + 3]
      );
    }
  }
  return 0;
}
