(function ($) {  // Require jQuery. Don't use global scope. (IIFE)
  'use strict';

  const DOM_SCOPE = document.body;  // Optional, for scoping this script.
  const N_KEEP_POINTS = 1000;  // # of plot points to keep in memory.

  function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  // Convert a "Pyodine JSON" data point into a CanvasJS plot point.
  function convertToPlotPoint(json_data_point) {
    return {x: new Date(json_data_point[0] * 1000),
            y: parseFloat(json_data_point[1])};
  }

  function updatePlot(plot_div, points, crop_time=N_KEEP_POINTS) {

    let div = $(plot_div);
    const display_time = document.getElementById('display_time').value;

    // For now, we are only using the first point of the received dataset, even
    // if it contains more. TODO allow adding more points at once.
    const newPoint = {x: new Date(points[0][0] * 1000),
      y: parseFloat(points[0][1])};

    if (typeof(div.data('chart')) !== 'undefined') {  // Plot exists, update it.
      const now = $('#use_server_clock:checked').length ? newPoint.x : new Date();
      const chart = div.data('chart');
      chart.options.data[0].dataPoints.push(newPoint);
      const age = (newPoint.x - chart.options.data[0].dataPoints[0].x) / 1000.0;
      if (age > crop_time) {
        chart.options.data[0].dataPoints = chart.options.data[0].dataPoints.slice(11);
      }
      // if (age > display_time) {
      chart.options.axisX.minimum = new Date(now - display_time * 1000);
      // }
      chart.options.axisX.maximum = now;
      chart.render();
    } else {  // Create new plot.
      const chart = new CanvasJS.Chart(plot_div, { 
        title: {
          text: plot_div.dataset['title'],
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
      $(plot_div).data('chart', chart);
    }
  }

  function updateOscPlot(plotDiv, readingsObj, cropTime=N_KEEP_POINTS) {

    let div = $(plotDiv);
    const displayTime = document.getElementById('display_time').value;

    const diodeCurrents =
      readingsObj[div.data('current1')].map(convertToPlotPoint);
    const tecCurrents =
      readingsObj[div.data('current2')].map(convertToPlotPoint);
    const temps =
      readingsObj[div.data('temp')].map(convertToPlotPoint);
    const temp_setpoint = parseFloat(readingsObj[div.data('tempSet')][0][1]);

    // Plot exists, update it.
    if (typeof(div.data('chart')) !== 'undefined') {
      const now =
        $('#use_server_clock:checked').length ? temps[0].x : new Date();
      const chart = div.data('chart');
      Array.prototype.push.apply(chart.options.data[0].dataPoints,
                                 diodeCurrents);
      Array.prototype.push.apply(chart.options.data[1].dataPoints,
                                 tecCurrents);
      Array.prototype.push.apply(chart.options.data[2].dataPoints,
                                 temps);

      // FIXME Update setpoint.

      // Crop off some points if we have too many points in memory.
      const age = (newPoint.x - chart.options.data[0].dataPoints[0].x) / 1000.0;
      if (age > crop_time) {
        chart.options.data[0].dataPoints = chart.options.data[0].dataPoints.slice(11);
      }

      // Render (visually update) plot.
      chart.options.axisX.minimum = new Date(now - display_time * 1000);
      chart.options.axisX.maximum = now;
      chart.render();
    }

    // Plot doesn't exist yet. Create it.
    else {
      const chart = new CanvasJS.Chart(plot_div, { 
        title: {
          text: div.data('title'),
        },
        data: [
          {  // diode current
            axisYType: 'secondary',
            dataPoints: diode_currents,
            lineColor: 'red',
            markerType: 'none',
            type: 'stepLine',
          },
          {  // tec current
            axisYType: 'secondary',
            dataPoints: tec_currents,
            lineColor: 'green',
            markerType: 'none',
            type: 'stepLine',
          },
          {  // temperature
            axisYType: 'primary',
            dataPoints: temperatures,
            lineColor: 'blue',
            markerType: 'none',
            type: 'spline',
          }
        ],
        interactivityEnabled: true,
        animationEnabled: true,
        axisX: {
          labelAngle: 30,
          gridThickness: 1,
        },
        axisY: {
          title: "Temp. in Menlo Units",
          gridThickness: 1,
          includeZero: false,
        },
        axisY2: {
          title: "Current in Menlo Units",
          gridThickness: 1,
          includeZero: false,
        },
      });
      chart.render();	
      $(plot_div).data('chart', chart);
    }
  }

  function updateAllPlots(new_values_obj) {

    // Gather available plot areas.
    let available_plots = {};
    $('div.plot',DOM_SCOPE).each(function(){
      available_plots[this.id] = this;
    });

    // Update them.
    for (const id in available_plots) {
      if (id in new_values_obj) {
        updatePlot(available_plots[id], new_values_obj[id]);
      } else {
        console.log(`Received message didn't include data to update plot "${id}"`)
      }
    }
  }

  function updateTexusFlags(new_values_obj) {
    for (const key in new_values_obj) {
      updateFlag(key, new_values_obj[key]);
    }
  }

  function updateFlag(entity_id, new_value) {
    const container = $(`tr[data-flag=${entity_id}]`);
    const indicators = $('td.indicator', container);
    if (new_value !== container.data('value')) {
      container.data('value', new_value);
      $('td.changed', container).html((new Date()).toLocaleTimeString())
    }
    indicators.html(new_value ? "On" : "Off");
    indicators.css('backgroundColor', new_value ? 'green' : 'red');
    $('td.updated', container).html((new Date()).toLocaleTimeString());
  }

  function sendFlag(ws, entityId, value) {
    const message = createMessage({
      method: 'setflag',
      args: [entityId, value]
    });
    sendMessage(ws, message);
  }

  function sendMessage(socket, message) {
    socket.send(message)
  }

  function createMessage(object, type) {
    const wrapper = {};
    wrapper.type = type;
    wrapper.checksum = '';
    wrapper.data = object;
    return JSON.stringify(wrapper) + '\n\n\n';
  }

  $(function(){  // Do things on page load.


    {  // Setup layout using jQuery UI.
      $('div.tabs').tabs();
    }

    let ws;  // Websocket connection.
    {  // Establish connection to server.
      const messageHandler = function(event) {
        const message = JSON.parse(event.data);
        switch (message.type) {
          case 'readings':
            updateAllPlots(message.data);
            $('div.osc_plot').each(function () {
              updateOscPlot(this, message.data);
            });
            break;
          case 'texus':
            updateTexusFlags(message.data);
            break;
          default:
            console.warn('Unknown message type "' + message.type + '".');
        }
      };

      $('#connect_btn').on('click', function() {
        const host = $('#host').val();
        const ws_port = $('#ws_port').val();
        ws = new WebSocket('ws://' + host + ':' + ws_port + '/');
        ws.onmessage = messageHandler;
      });
    }


    {  // Setup interactive UI elements.
      $('div.slider').each(function() {
        const container = $(this);
        const handle = $('.ui-slider-handle', container);
        container.slider({
          min: 0,
          max: 360,
          step: 0.1,
          create: function() {
            handle.text(container.slider("value") + " °");
          },
          slide: function(event, ui) {
            handle.text(ui.value + " °");
          }
        });
      });
      $('#send_btn').on('click', function() {
        const message = $('#send_data').val();
        console.log("Sending: " + message);
        sendMessage(ws, message);
      });

      $('tr[data-flag]').each(function(){
        const container = $(this);
        $('.switch', this).on('click', function() {
          sendFlag(ws, container.data('flag'), $(this).hasClass('on'));
        });
      });

      // TOOLS

      $('[data-safety-switch]').each(function(){
        const sswitch = $(this);
        const controls = $(sswitch.data('safetySwitch'));
        controls.prop('disabled', true);
        sswitch.on('change', function() {
          controls.prop('disabled', this.checked ? false : true);
        });
        controls.on('click', function() {
          sswitch.prop('checked', false);
          sswitch.trigger('change');
        });
      });
    }
  });

})(jQuery);
