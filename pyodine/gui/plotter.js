/* eslint-env es6, browser, jquery */
/* global CanvasJS */

const N_KEEP_POINTS = 2000;  // I'm craving for ES7 modules to avoid globals.

class Plotter {  // eslint-disable-line no-unused-vars
  // Convert a "Pyodine JSON" data point into a CanvasJS plot point.
  static convertToPlotPoint(jsonDataPoint) {
    return {
      x: new Date(jsonDataPoint[0] * 1000),
      y: parseFloat(jsonDataPoint[1]),
    };
  }

  // Crop off some points if we have too many points in memory.
  static truncatePlotDataToSaveMemory(chart, nKeep = N_KEEP_POINTS) {
    chart.options.data.forEach((dataSet) => {
      const excess = dataSet.dataPoints.length - nKeep;

      // Do not truncate on every iteration but allow for a 20% overflow
      // instead.
      if (excess > nKeep * 0.2) {
        dataSet.dataPoints = dataSet.dataPoints.slice(excess);
      }
    });
  }

  static updatePlot(plotDiv, points) {
    const div = $(plotDiv);
    const displayTime = document.getElementById('display_time').value;

    if (!points.length) return;

    // For now, we are only using the first point of the received dataset, even
    // if it contains more. TODO allow adding more points at once.
    const newPoint = {
      x: new Date(points[0][0] * 1000),
      y: parseFloat(points[0][1]),
    };

    if (typeof div.data('chart') !== 'undefined') {  // Plot exists, update it.
      const now = $('#use_server_clock:checked').length ? newPoint.x : new Date();
      const chart = div.data('chart');
      chart.options.data[0].dataPoints.push(newPoint);

      Plotter.truncatePlotDataToSaveMemory(chart);

      // if (age > displayTime) {
      chart.options.axisX.minimum = new Date(now - (displayTime * 1000));
      // }
      chart.options.axisX.maximum = now;
      chart.render();
    } else {  // Create new plot.
      const chart = new CanvasJS.Chart(plotDiv, {
        title: {
          text: plotDiv.dataset.title,
        },
        data: [{
          type: 'stepLine',
          axisYType: 'secondary',
          dataPoints: [newPoint],
          markerType: 'none',
        }],
        interactivityEnabled: true,
        animationEnabled: true,
        axisX: {
          labelAngle: 30,
          gridThickness: 1,
        },
        axisY2: {
          title: div.data('ylabel'),
          gridThickness: 1,
          includeZero: false,
        },
      });
      chart.render();
      $(plotDiv).data('chart', chart);
    }
  }

  static updatePiiPlot(plotDiv, readingsObj) {
    // Check if the message we received actually contains any data. If there is
    // a problem with subsystems, we might well have received an empty object.
    if (Object.keys(readingsObj).length === 0) {
      console.log("Couldn't update Lockbox plot, no data was received.");
      return;
    }
    const div = $(plotDiv);
    const displayTime = document.getElementById('display_time').value;
    const prefix = plotDiv.dataset.unitName;
    if (!prefix) return;
    const monitorVals = readingsObj[`${prefix}_monitor`].map(Plotter.convertToPlotPoint);
    const pMonitorVals = readingsObj[`${prefix}_p_monitor`].map(Plotter.convertToPlotPoint);
    if (typeof div.data('chart') === 'undefined') {
      // Create a new plot.
      const chart = new CanvasJS.Chart(plotDiv, {
        data: [
          {  // Monitor
            dataPoints: monitorVals,
            legendText: "Full Loop Monitor",
            markerType: 'none',
            showInLegend: true,
            type: 'stepLine',
          },
          {  // P Monitor
            dataPoints: pMonitorVals,
            legendText: "P Monitor",
            markerType: 'none',
            showInLegend: true,
            type: 'stepLine',
          },
        ],
        axisX: {
          labelAngle: 30,
          gridThickness: 1,
        },
        axisY: {
          title: "Amplitude in mV",
          gridThickness: 1,
        },
        legend: {},
      });
      chart.render();
      $(plotDiv).data('chart', chart);
    } else {  // Update the existing plot.
      const useRemoteTime =
        $('#use_server_clock:checked').length && monitorVals.length;
      const now = useRemoteTime ? monitorVals[0].x : new Date();
      const chart = div.data('chart');
      Array.prototype.push.apply(chart.options.data[0].dataPoints, monitorVals);
      Array.prototype.push.apply(chart.options.data[1].dataPoints, pMonitorVals);

      Plotter.truncatePlotDataToSaveMemory(chart);

      // Render (visually update) plot.
      chart.options.axisX.minimum = new Date(now - (displayTime * 1000));
      chart.options.axisX.maximum = now;
      chart.render();
    }
  }

  static updateAllPlots(newValuesObj) {
    // Gather available plot areas.
    const availablePlots = {};
    $('div.plot').each(function register() {
      availablePlots[this.id] = this;
    });

    // Update them.
    Object.keys(availablePlots).forEach((id) => {
      if (id in newValuesObj) {
        Plotter.updatePlot(availablePlots[id], newValuesObj[id]);
      }
    });
  }

  static updateOscPlot(plotDiv, readingsObj) {
    const div = $(plotDiv);
    const displayTime = document.getElementById('display_time').value;
    const fields = plotDiv.dataset;
    const hasCurrentDriver = 'current1' in fields && 'current1Set' in fields;

    function harvestField(fieldName) {
      if (fields[fieldName] in readingsObj) {
        return readingsObj[fields[fieldName]].map(Plotter.convertToPlotPoint);
      }
      return [];
    }
    const diodeCurrents = harvestField('current1');
    const currentSetpoints = harvestField('current1Set');
    const tecCurrents = harvestField('tecCurrent');
    const temps = harvestField('temp');
    const tempSetpoints = harvestField('tempSet');
    const tempRawSetpoints = harvestField('tempRawSet');

    // Plot exists, update it.
    if (typeof (div.data('chart')) !== 'undefined') {
      let now;
      if ($('#use_server_clock:checked').length && temps.length) {
        now = temps[0].x;
      } else {
        now = new Date();
      }
      const chart = div.data('chart');
      Array.prototype.push.apply(chart.options.data[0].dataPoints, temps);
      Array.prototype.push.apply(chart.options.data[1].dataPoints, tempRawSetpoints);
      Array.prototype.push.apply(chart.options.data[2].dataPoints, tecCurrents);
      if (hasCurrentDriver) {
        Array.prototype.push.apply(chart.options.data[3].dataPoints, diodeCurrents);
      }

      // Upate setpoint indicator lines.
      if (tempSetpoints.length) {
        chart.options.axisY.stripLines[0].value = tempSetpoints[0].y;
      }
      if (hasCurrentDriver && currentSetpoints.length) {
        chart.options.axisY2.stripLines[0].value = currentSetpoints[0].y;
      }

      Plotter.truncatePlotDataToSaveMemory(chart);

      // Render (visually update) plot.
      chart.options.axisX.minimum = new Date(now - (displayTime * 1000));
      chart.options.axisX.maximum = now;
      chart.render();
    } else {  // Plot doesn't exist yet. Create it.
      const data = [];
      data.push({  // temperature
        axisYType: 'primary',
        axisYIndex: 1,
        dataPoints: temps,
        legendText: "Temperature",
        markerType: 'none',
        showInLegend: true,
        type: 'line',
      });
      data.push({  // temperature setpoint
        axisYType: 'primary',
        axisYIndex: 1,
        dataPoints: tempRawSetpoints,
        legendText: "Temp. Setpoint",
        markerType: 'none',
        showInLegend: true,
        type: 'stepLine',
      });
      data.push({  // TEC current
        axisYType: 'secondary',
        axisYIndex: 0,
        dataPoints: tecCurrents,
        legendText: "Peltier current",
        markerType: 'none',
        showInLegend: true,
        type: 'stepLine',
      });
      if (hasCurrentDriver) {
        data.push({  // diode current
          axisYType: 'secondary',
          axisYIndex: 0,
          dataPoints: diodeCurrents,
          legendText: "Diode current",
          markerType: 'none',
          showInLegend: true,
          type: 'stepLine',
        });
      }
      const chart = new CanvasJS.Chart(plotDiv, {
        data,
        interactivityEnabled: true,
        animationEnabled: true,
        axisX: {
          labelAngle: 30,
          gridThickness: 1,
        },
        axisY: {
          title: "Temp. in °C",
          gridThickness: 1,
          includeZero: false,
          stripLines: [{
            value: tempSetpoints.length ? tempSetpoints[0].y : '',
            label: "Temp. Setpoint",
            labelAlign: 'near',
            lineDashType: 'dot',
            showOnTop: true,
          }],
        },
        axisY2: {
          title: "I in mA",
          gridThickness: 1,
          gridDashType: 'dash',
          includeZero: false,
          stripLines: hasCurrentDriver ? [{
            value: currentSetpoints.length ? currentSetpoints[0].y : '',
            label: "Diode Current Setpoint",
            labelAlign: 'near',
            lineDashType: 'dot',
            showOnTop: true,
          }] : [],
        },
        legend: {},
      });
      chart.render();
      $(plotDiv).data('chart', chart);
    }
  }

  static updateSignalPlot(plotDiv, data, plotXY = true) {
    const sortedData = data.sort((pointA, pointB) => pointA[0] - pointB[0]);
    const plotData = [
      plotXY ? {
        axisYType: 'primary',
        type: "line",
        dataPoints: sortedData.map(point => ({ x: point[0], y: point[1] })),
      } : {},
      plotXY && (sortedData[0].length > 2) ? {
        axisYType: 'secondary',
        type: "scatter",
        dataPoints: sortedData.map(point => ({ x: point[0], y: point[2] })),
      } : {},
      plotXY ? {} : {
        type: "line",
        dataPoints: data.map(point => ({ y: point[0] })),
      },
      plotXY ? {} : {
        type: "line",
        dataPoints: data.map(point => ({ y: point[1] })),
      },
    ];
    const chart = new CanvasJS.Chart(plotDiv, {
      axisX: { title: "Frequency in a.u." },
      axisY: { title: "MTS Signal" },
      axisY2: { title: "Pump Signal", includeZero: false },
      title: { text: "Error Signal" },
      data: plotData,
    });
    chart.render();
    $(plotDiv).data('chart', chart);
  }
}

