/* eslint-env es6, browser, jquery */
/* eslint no-alert: "off" */
/* eslint no-lone-blocks: "off" */
/* global CanvasJS */

// Require jQuery. Don't use global scope. (IIFE)
(function jqueryWrapper($) {
  'use strict';

  const DOM_SCOPE = document.body;  // Optional, for scoping this script.
  const N_KEEP_POINTS = 2000;  // # of plot points to keep in memory.

  function createMessage(object, type) {
    const wrapper = {};
    wrapper.type = type;
    wrapper.checksum = '';
    wrapper.data = object;
    return `${JSON.stringify(wrapper)}\n\n\n`;
  }

  function callRemoteMethod(socket, methodName, args) {
    const msg = createMessage({
      method: methodName,
      args,
    });
    socket.send(msg);
  }

  // Convert a "Pyodine JSON" data point into a CanvasJS plot point.
  function convertToPlotPoint(jsonDataPoint) {
    return {
      x: new Date(jsonDataPoint[0] * 1000),
      y: parseFloat(jsonDataPoint[1]),
    };
  }

  // Crop off some points if we have too many points in memory.
  function truncatePlotDataToSaveMemory(chart, nKeep = N_KEEP_POINTS) {
    chart.options.data.forEach((dataSet) => {
      const excess = dataSet.dataPoints.length - nKeep;

      // Do not truncate on every iteration but allow for a 20% overflow
      // instead.
      if (excess > nKeep * 0.2) {
        dataSet.dataPoints = dataSet.dataPoints.slice(excess);
      }
    });
  }

  function updatePlot(plotDiv, points) {
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

      truncatePlotDataToSaveMemory(chart);

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

  function updateOscPlot(plotDiv, readingsObj) {
    const div = $(plotDiv);
    const displayTime = document.getElementById('display_time').value;

    const diodeCurrents =
      readingsObj[div.data('current1')].map(convertToPlotPoint);
    const tecCurrents =
      readingsObj[div.data('current2')].map(convertToPlotPoint);
    const temps =
      readingsObj[div.data('temp')].map(convertToPlotPoint);
    const tempSetpoints =
      readingsObj[div.data('tempSet')].map(convertToPlotPoint);
    const tempRawSetpoints =
      readingsObj[div.data('tempRawSet')].map(convertToPlotPoint);
    const currentSetpoints =
      readingsObj[div.data('current1Set')].map(convertToPlotPoint);

    // Plot exists, update it.
    if (typeof (div.data('chart')) !== 'undefined') {
      const now =
        $('#use_server_clock:checked').length ? temps[0].x : new Date();
      const chart = div.data('chart');
      Array.prototype.push.apply(chart.options.data[0].dataPoints,
                                 diodeCurrents);
      Array.prototype.push.apply(chart.options.data[1].dataPoints,
                                 tecCurrents);
      Array.prototype.push.apply(chart.options.data[2].dataPoints, temps);
      Array.prototype.push.apply(chart.options.data[3].dataPoints,
                                 tempRawSetpoints);

      // Upate setpoint indicator lines.
      if (tempSetpoints.length) {
        chart.options.axisY.stripLines[0].value = tempSetpoints[0].y;
      }
      if (currentSetpoints.length) {
        chart.options.axisY2.stripLines[0].value = currentSetpoints[0].y;
      }

      truncatePlotDataToSaveMemory(chart);

      // Render (visually update) plot.
      chart.options.axisX.minimum = new Date(now - (displayTime * 1000));
      chart.options.axisX.maximum = now;
      chart.render();
    } else {  // Plot doesn't exist yet. Create it.
      const chart = new CanvasJS.Chart(plotDiv, {
        data: [
          {  // diode current
            axisYType: 'secondary',
            axisYIndex: 0,
            dataPoints: diodeCurrents,
            legendText: "Diode current",
            markerType: 'none',
            showInLegend: true,
            type: 'stepLine',
          },
          {  // tec current
            axisYType: 'secondary',
            axisYIndex: 0,
            dataPoints: tecCurrents,
            legendText: "Peltier current",
            markerType: 'none',
            showInLegend: true,
            type: 'stepLine',
          },
          {  // temperature
            axisYType: 'primary',
            axisYIndex: 1,
            dataPoints: temps,
            legendText: "Temperature",
            markerType: 'none',
            showInLegend: true,
            type: 'line',
          },
          {  // temperature setpoint
            axisYType: 'primary',
            axisYIndex: 1,
            dataPoints: tempRawSetpoints,
            legendText: "Temp. Setpoint",
            markerType: 'none',
            showInLegend: true,
            type: 'stepLine',
          },
        ],
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
            value: tempSetpoints.length ? tempSetpoints[0].y : null,
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
          stripLines: [{
            value: currentSetpoints[0].y,
            label: "Diode Current Setpoint",
            labelAlign: 'near',
            lineDashType: 'dot',
            showOnTop: true,
          }],
        },
        legend: {},
      });
      chart.render();
      $(plotDiv).data('chart', chart);
    }
  }

  function updatePiiPlot(plotDiv, readingsObj) {
    const div = $(plotDiv);
    const displayTime = document.getElementById('display_time').value;
    const prefix = plotDiv.dataset['unitName'];
    if (!prefix) return;
    const monitorVals = readingsObj[`${prefix}_monitor`].map(
      convertToPlotPoint);
    const pMonitorVals = readingsObj[`${prefix}_p_monitor`].map(
      convertToPlotPoint);
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

      truncatePlotDataToSaveMemory(chart);

      // Render (visually update) plot.
      chart.options.axisX.minimum = new Date(now - (displayTime * 1000));
      chart.options.axisX.maximum = now;
      chart.render();
    }
  }

  function updateAllPlots(newValuesObj) {
    // Gather available plot areas.
    const availablePlots = {};
    $('div.plot', DOM_SCOPE).each(function register() {
      availablePlots[this.id] = this;
    });

    // Update them.
    Object.keys(availablePlots).forEach((id) => {
      if (id in newValuesObj) {
        updatePlot(availablePlots[id], newValuesObj[id]);
      }
    });
  }

  function updateIndicator(elm, isOn) {
    const onText = elm.data('textTrue') || "ON";
    const offText = elm.data('textFalse') || "OFF";
    elm.html(isOn ? onText : offText);
    elm.css('backgroundColor', isOn ? 'green' : 'red');
  }

  function updateFlag(entityId, newValue) {
    const container = $(`tr[data-flag=${entityId}]`);
    if (newValue !== container.data('value')) {
      container.data('value', newValue);
      $('td.changed', container).html((new Date()).toLocaleTimeString());
    }
    updateIndicator($('td.indicator', container), newValue === 1);
    $('td.updated', container).html((new Date()).toLocaleTimeString());
  }

  function updateTexusFlags(newValuesObj) {
    Object.keys(newValuesObj).forEach((key) => {
      updateFlag(key, newValuesObj[key]);
    });
  }

  function sendFlag(socket, entityId, value) {
    callRemoteMethod(socket, 'setflag', [entityId, value]);
  }

  function updateIndicators(newValuesObj) {
    const booleanIndicators = $("td.indicator[data-qty]");
    booleanIndicators.each(function update() {
      const qty = this.dataset.qty;
      if (qty in newValuesObj) {
        if (newValuesObj[qty].length > 0) {
          // Get the value ([1]) of the latest ([0]) data point.
          updateIndicator($(this), newValuesObj[qty][0][1] === 1);

          // Update "last updated" fields if any are present for qty.
          const timeOfMeasurement = new Date(newValuesObj[qty][0][0] * 1000);
          $(`.update_indicator[data-qty=${qty}]`).html(
            timeOfMeasurement.toLocaleTimeString());
        }
        console.log(
          `Couldn't update indicator for ${qty}, as empty dataset was received`);
      }
      console.log(
        `Couldn't update indicator for ${qty}, as no data was received`);
    });

    const setPointFields = document.querySelectorAll('input.source[data-qty]');
    setPointFields.forEach((input) => {
      if (input.disabled) {
        const setQtyKey = `${input.dataset.qty}_set`;

        // Timeline of recent values for this specific setpoint.
        // @type {Buffer}
        const setpoints = newValuesObj[setQtyKey];
        if (setpoints && setpoints.length) {
          input.value = setpoints[0][1];
        }
      }
    });
  }

  $(() => {  // Do things on page load.
    // Setup layout using jQuery UI.
    $('div.tabs').tabs();

    let ws;  // Websocket connection.
    {  // Establish connection to server.
      const handler = function messageHandler(event) {
        const message = JSON.parse(event.data);
        switch (message.type) {
          case 'readings':
            updateAllPlots(message.data);
            $('div.osc_plot').each(function plotUpdater() {
              updateOscPlot(this, message.data);
            });
            document.querySelectorAll('div.pii.plot[data-unit-name]').forEach(
              plotDiv => updatePiiPlot(plotDiv, message.data));
            updateIndicators(message.data);
            break;
          case 'texus':
            updateTexusFlags(message.data);
            break;
          default:
            console.warn(`Unknown message type "${message.type}".`);
        }
      };

      $('#connect_btn').on('click', () => {
        const host = $('#host').val();
        const wsPort = $('#ws_port').val();
        ws = new WebSocket(`ws://${host}:${wsPort}/`);
        ws.onmessage = handler;
      });
    }


    {  // Setup interactive UI elements.
      $('div.slider').each(function setupSlider() {
        const container = $(this);
        const handle = $('.ui-slider-handle', container);
        container.slider({
          min: 0,
          max: 360,
          step: 0.1,
          create() {
            handle.text(`${container.slider("value")} °`);
          },
          slide(event, ui) {
            handle.text(`${ui.value} °`);
          },
        });
      });

      // Setup send buttons in special "flag" table rows.
      $('tr[data-flag]').each(function armSendFlagBtns() {
        const container = $(this);
        $('.switch', this).on('click', function send() {
          sendFlag(ws, container.data('flag'), $(this).hasClass('on'));
        });
      });

      $('input[type=button].setter[data-qty]').each(function armSetterBtn() {
        const qty = this.dataset.qty;
        const trigger = $(this);
        const source = $(`input.source[data-qty=${qty}]`).first();
        trigger.on('click', () => {
          const value = source.val();
          if (value !== '') {
            callRemoteMethod(ws, `set_${qty}`, [value]);
          } else {
            alert("No value set. Please set a value.");
          }
        });
      });

      $('input[type=button][data-method][data-arguments]').each(
        function armMethodCallBtn() {
          const button = $(this);
          button.on('click', () => {
            const commandName = button.data('method');
            const args = button.data('arguments');
            callRemoteMethod(ws, commandName, args);
          });
        });

      // TOOLS

      $('[data-safety-switch]').each(function armSafetySwitch() {
        const sswitch = $(this);
        const controls = $(sswitch.data('safetySwitch')).filter('input');
        controls.prop('disabled', true);
        sswitch.on('change', () => {
          // Outer "this" is accessed, as we are in an arrow function.
          controls.prop('disabled', !this.checked);
        });
        controls.on('click', function armControlBtn() {
          if (this.type === 'button') {
            sswitch.prop('checked', false);
            sswitch.trigger('change');
          }
        });
      });
    }
  });
}(jQuery));
