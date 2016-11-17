"""Visualizes the Allan Variance of a given dataset.
"""

import numpy as np
from datetime import datetime
# import csv  # to read the CSV-style input files (.dat etc..)
# import allantools  # https://github.com/aewallin/allantools


class Measurement:
    def __init__(
            self, times: iter,
            frequencies: iter,
            start_time: datetime=None,
            end_time: datetime=None,
            step_size: int=None) -> None:
        self.times = times
        self.freqs = frequencies
        self.start_time = start_time
        self.end_time = end_time
        self.step_size = step_size

    def get_times(self) -> iter:
        return self.times

    def get_frequencies(self) -> iter:
        return self.freqs

    def plot_avar(self) -> None:
        print(self.freqs)
        pass


def parse_counter_dat(filename: str) -> Measurement:
    times, freqs = np.loadtxt(filename, usecols=(1, 3), skiprows=2,
                              unpack=True)
    msmnt = Measurement(times=times, frequencies=freqs)
    return msmnt
