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

  function updatePlot(plotDiv, points, cropTime=N_KEEP_POINTS) {

    let div = $(plotDiv);
    const display_time = document.getElementById('display_time').value;

    // For now, we are only using the first point of the received dataset, even
    // if it contains more. TODO allow adding more points at once.
    const newPoint = {
      x: new Date(points[0][0] * 1000),
      y: parseFloat(points[0][1])
    };

    if (typeof(div.data('chart')) !== 'undefined') {  // Plot exists, update it.
      const now = $('#use_server_clock:checked').length ? newPoint.x : new Date();
      const chart = div.data('chart');
      chart.options.data[0].dataPoints.push(newPoint);
      const age = (newPoint.x - chart.options.data[0].dataPoints[0].x) / 1000.0;
      if (age > cropTime) {
        chart.options.data[0].dataPoints = chart.options.data[0].dataPoints.slice(11);
      }
      // if (age > display_time) {
      chart.options.axisX.minimum = new Date(now - display_time * 1000);
      // }
      chart.options.axisX.maximum = now;
      chart.render();
    } else {  // Create new plot.
      const chart = new CanvasJS.Chart(plotDiv, { 
        title: {
          text: plotDiv.dataset['title'],
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
      const age = (temps[0].x - chart.options.data[0].dataPoints[0].x) / 1000.0;
      if (age > cropTime) {
        chart.options.data[0].dataPoints = chart.options.data[0].dataPoints.slice(11);
      }

      // Render (visually update) plot.
      chart.options.axisX.minimum = new Date(now - displayTime * 1000);
      chart.options.axisX.maximum = now;
      chart.render();
    }

    // Plot doesn't exist yet. Create it.
    else {
      const chart = new CanvasJS.Chart(plotDiv, { 
        // title: {
        //   text: div.data('title'),
        // },
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
            type: 'stepLine',
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
          gridDashType: 'dash',
          includeZero: false,
        },
        legend: {},
      });
      chart.render();	
      $(plotDiv).data('chart', chart);
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
    if (new_value !== container.data('value')) {
      container.data('value', new_value);
      $('td.changed', container).html((new Date()).toLocaleTimeString())
    }
    updateIndicator($('td.indicator', container), new_value == '1')
    $('td.updated', container).html((new Date()).toLocaleTimeString());
  }

  function updateIndicator (elm, is_on) {
    elm.html(is_on ? "On" : "Off");
    elm.css('backgroundColor', is_on ? 'green' : 'red');
  }

  function sendFlag(socket, entityId, value) {
    callRemoteMethod(socket, 'setflag', [entityId, value]);
  }

  function createMessage(object, type) {
    const wrapper = {};
    wrapper.type = type;
    wrapper.checksum = '';
    wrapper.data = object;
    return JSON.stringify(wrapper) + '\n\n\n';
  }

  function callRemoteMethod (socket, methodName, args) {
    const msg = createMessage({
      method: method,
      args: args
    });
    socket.send(msg);
  }

  function updateIndicators(newValuesObj) {
    $("td.indicator[data-qty]").each(function () {
      const qty = this.dataset.qty;
      if (qty in newValuesObj) {
        if (newValuesObj[qty].length > 0) {

          // Get the value ([1]) of the latest ([0]) data point.
          updateIndicator($(this), newValuesObj[qty][0][1] == '1');

          // Update "last updated" fields if any are present for qty.
          const timeOfMeasurement = new Date(newValuesObj[qty][0][0] * 1000);
          $('.update_indicator[data-qty=' + qty + ']').html(
            timeOfMeasurement.toLocaleTimeString());
        }
      }
    });
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
            updateIndicators(message.data);
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

      $('tr[data-flag]').each(function(){
        const container = $(this);
        $('.switch', this).on('click', function() {
          sendFlag(ws, container.data('flag'), $(this).hasClass('on'));
        });
      });

      $('input[type=button].setter[data-qty]').each(function () {
        const qty = this.dataset.qty;
        const trigger = $(this);
        const source = $('input.source[data-qty=' + qty + ']').first();
        const value = source.val();
        trigger.on('click', function () {
          if (value != '') {
            callRemoteMethod(ws, 'set' + qty, value)
          } else {
            alert("No value set. Please set a value.")
          }
        });
      });


      // TOOLS

      $('[data-safety-switch]').each(function(){
        const sswitch = $(this);
        const controls = $(sswitch.data('safetySwitch')).filter('input');
        controls.prop('disabled', true);
        sswitch.on('change', function() {
          controls.prop('disabled', this.checked ? false : true);
        });
        controls.on('click', function() {
          if (this.type == 'button') {
            sswitch.prop('checked', false);
            sswitch.trigger('change');
          }
        });
      });
    }
  });

})(jQuery);
