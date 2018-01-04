"""Parses various freq. time series input into "Measurement" objects."""

import numpy as np
import matplotlib.pyplot as plt
import allantools  # https://github.com/aewallin/allantools


class Measurement:
    def __init__(self, times: iter=[], frequencies: iter=[]) -> None:
        self._times = times
        self._freqs = frequencies
        self._gate_time = None
        self.start_time = None
        self.end_time = None

    @property
    def times(self) -> iter:
        """The times at which the values were recorded."""
        return self._times

    @times.setter
    def times(self, time_values: iter) -> None:
        self._times = time_values

    @property
    def frequencies(self) -> iter:
        """The frequency values at the times specified in ``.times``."""
        return self._freqs

    @frequencies.setter
    def frequencies(self, frequency_values: iter) -> None:
        self._freqs = frequency_values

    @property
    def gate_time(self) -> float:
        return self._gate_time

    @gate_time.setter
    def gate_time(self, time: float) -> None:
        self._gate_time = time

    def plot_frequency(self) -> None:
        """Opens a Pyplot plot drawing frequency over time."""
        plt.plot(self.times, self.frequencies)
        plt.ylabel('Frequency in Hz')
        plt.xlabel('Elapsed Time in s')
        plt.show()

    def plot_adev(self) -> None:
        """Opens a Pyplot showing the non-overlappint Allan variance."""
        taus, adev, _, _ = allantools.adev(self.frequencies, data_type='freq',
                                           rate=self.gate_time)
        plt.plot(taus, adev)
        plt.xlabel('Integration Time in s')
        plt.ylabel('Non-Overlapping Allan Variance')
        plt.xscale('log')
        plt.yscale('log')
        plt.show()


def from_counter_dat(filename: str) -> Measurement:
    times, freqs = np.loadtxt(filename, usecols=(1, 3), skiprows=2,
                              unpack=True)
    msmnt = Measurement(times=times, frequencies=freqs)
    return msmnt


def from_cnt91_txt(filename: str) -> Measurement:
    times, freqs = np.loadtxt(filename, usecols=(0, 1), skiprows=1,
                              unpack=True)
    msmnt = Measurement(times=times, frequencies=freqs)
    msmnt.gate_time = times[1] - times[0]
    return msmnt
