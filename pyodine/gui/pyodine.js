/* eslint-env es6, browser, jquery */
/* eslint no-alert: "off" */
/* eslint no-lone-blocks: "off" */
/* global Plotter */
/* global FbgUtil */
/* global JustGage */

// Require jQuery. Don't use global scope. (IIFE)
(function scopeWrapper() {
  'use strict';

  // Provide a global variable to access the websocket connection although it's
  // not connected yet. We can't just use "conn = null;" as reassignment will
  // kill the references.
  const CONNECTION = { ws: null };

  const runlevelGages = { requested: null, reported: null };
  const LEVEL_NAMES = ["UNDEFINED", "SHUTDOWN", "STANDBY", "AMBIENT", "HOT",
    "PRELOCK", "LOCK", "BALANCED"];

  function createMessage(object, type) {
    const wrapper = {};
    wrapper.type = type;
    wrapper.checksum = '';
    wrapper.data = object;
    return `${JSON.stringify(wrapper)}\n\n\n`;
  }

  function callRemoteMethod(conn, methodName, args) {
    const msg = createMessage({
      method: methodName,
      args,
    });
    conn.ws.send(msg);
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
      $('td.changed', container).html((new Date()).toLocaleTimeString());
    }
    updateIndicator($('td.indicator', container), newValue);
    container.data('value', newValue);
    $('td.updated', container).html((new Date()).toLocaleTimeString());
  }

  const updateRunlevel = function (requested, reported) {
    runlevelGages.requested.refresh(requested);
    runlevelGages.reported.refresh(reported);
  };

  const setupRunlevelGauges = function () {
    runlevelGages.requested = new JustGage({
      id: 'requested_runlevel',
      label: "Requested",
      max: 7,
      min: 0,
      pointer: true,
      textRenderer: level => LEVEL_NAMES[level],
      value: 0,
    });
    runlevelGages.reported = new JustGage({
      id: 'reported_runlevel',
      label: "Reported",
      max: 7,
      min: 0,
      pointer: true,
      textRenderer: level => LEVEL_NAMES[level],
      value: 0,
    });
  };

  function updateTexusFlags(newValuesObj) {
    Object.keys(newValuesObj).forEach((key) => {
      updateFlag(key, newValuesObj[key]);
    });
  }

  function sendFlag(conn, entityId, value) {
    callRemoteMethod(conn, 'setflag', [entityId, value]);
  }

  /**
   * Update all indicators for which there are new values in the given data.
   */
  function updateIndicators(newValuesObj) {
    // Boolean indicators
    const booleanIndicators = $(".indicator[data-qty]");
    booleanIndicators.each(function update() {
      const qty = this.dataset.qty;
      if (!(qty in newValuesObj) || newValuesObj[qty].length === 0) return;

      // Get the value ([1]) of the latest ([0]) data point.
      updateIndicator($(this), newValuesObj[qty][0][1] === 1);

      // Update "last updated" fields if any are present for qty.
      const timeOfMeasurement = new Date(newValuesObj[qty][0][0] * 1000);
      $(`.update_indicator[data-qty=${qty}]`).html(timeOfMeasurement.toLocaleTimeString());
    });

    // General indicators
    document.querySelectorAll('input.source[data-qty]').forEach((input) => {
      if (input.disabled) {
        // Timeline of recent values for this specific setpoint.
        // @type {Buffer}
        const setpoints = newValuesObj[input.dataset.qty];
        if (setpoints && setpoints.length) {
          input.value = setpoints[0][1];
        }
      }
    });
  }

  // Parse "readings"-type data package and dispatch associated handlers.
  // @param {Object} data The message payload as  extracted from the received
  //                      JSON message.
  function parseReadings(data) {
    Plotter.updateAllPlots(data);
    $('div.osc_plot').each(function plotUpdater() {
      Plotter.updateOscPlot(this, data);
    });
    document.querySelectorAll('div.pii.plot[data-unit-name]')
      .forEach(plotDiv => Plotter.updatePiiPlot(plotDiv, data));
    updateIndicators(data);
  }

  // Parse "signal"-type data package and dispatch associated handlers.
  // @param {Object} data The message payload as  extracted from the received
  //                      JSON message.
  function parseSignal(data) {
    const intData = Array.from(FbgUtil.base64toUint16(data.data));
    const normalizedData = intData.map(entry => (entry - (2 ** 15)) / (2 ** 15));
    const nChannels = data.shape[1];  // # of readings per sample.
    const plotXY = document.getElementById('plotVsRamp').checked;

    Plotter.updateSignalPlot(
      document.getElementById('signalPlot'),
      // Unpack serial data into x and y values.
      FbgUtil.reshapeArray(normalizedData, nChannels),
      plotXY,
    );
  }

  // Parse a received JSON data package and pass the contents on to dedicated
  // handler functions.
  // @param {Object} event contains the data to be parsed at event.data (a
  //                       string)
  // @returns null
  function messageHandler(event) {
    const message = JSON.parse(event.data);
    switch (message.type) {
      case 'readings':
        parseReadings(message.data);
        break;
      case 'setup':
        updateIndicators(message.data);
        break;
      case 'signal':
        parseSignal(message.data);
        break;
      case 'texus':
        updateTexusFlags(message.data);
        break;
      case 'aux_temps':
        Plotter.updateTemperatureMonitor(document.getElementById('temp_monitor'), message.data);
        break;
      default:
        console.warn(`Unknown message type "${message.type}".`);
    }
  }

  /**
   * Setup the interactive "host selector" dropdown for the IP address to
   * connect to.
   */
  function setupHostSelector() {
    // Extract the actual IP address from the host dropdown selector.
    const operateHostSelector = (selectElm) => {
      const ipInput = document.getElementsByName('ip')[0];
      ipInput.value = selectElm.value;
      ipInput.style.display = (selectElm.value === '') ? 'inline' : 'none';
    };

    const hostSelector = document.getElementsByName('host')[0];
    operateHostSelector(hostSelector);
    hostSelector.addEventListener(
      'change',
      event => operateHostSelector(event.target),
    );
  }

  function armSetterBtns(conn) {
    $('input[type=button].setter[data-qty]').each(function armSetterBtn() {
      const qty = this.dataset.qty;
      const trigger = $(this);

      // Find the input element containing the value to be sent.
      const source = $(`input.source[data-qty=${qty}]`).first();

      trigger.on('click', () => {
        const value = source.val();
        if (value !== '') {
          callRemoteMethod(conn, `set_${qty}`, [value]);
        } else {
          alert("No value set. Please set a value.");
        }
      });
    });
  }

  function sendModDemodSettings(websocket) {
    const eomFreq = $('input[data-qty=eom_freq]').val();
    const freqOffset = 0.001 * $('input[data-qty=mixer_offset_freq]').val();

    // Set mixer to same frequency as EOM or slightly offset if requested.
    const mixerFreq = (freqOffset > 0) ? eomFreq - freqOffset : eomFreq;
    const period = 1 / eomFreq;  // Period time of RF signal (360°) in μs

    // Get the desired phase shift between EOM and mixer in both milliseconds
    // and degrees.
    const phaseShiftMs = $('input[data-qty=mixer_phase_us]').val();
    const phaseShiftDeg = ((phaseShiftMs / period) * 360) % 360;

    // Send computed values to server.
    callRemoteMethod(websocket, 'set_eom_freq', [eomFreq]);
    callRemoteMethod(websocket, 'set_mixer_freq', [mixerFreq]);
    callRemoteMethod(websocket, 'set_mixer_phase', [phaseShiftDeg]);
    console.log([eomFreq, mixerFreq, phaseShiftDeg]);

    // Update input hint.
    $('#ms_per_cycle').html(period);
  }


  $(() => {  // Do things on page load.
    // Setup layout using jQuery UI.
    $('div.tabs').tabs();

    // Establish connection to server.
    $('#connect_btn').on('click', () => {
      const host = document.getElementsByName('ip')[0].value;
      const wsPort = document.getElementById('ws_port').value;
      CONNECTION.ws = new WebSocket(`ws://${host}:${wsPort}/`);
      CONNECTION.ws.onmessage = messageHandler;
    });
    $('#disconnect_btn').on('click', () => {
      CONNECTION.ws.close();
    });

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

      setupHostSelector();

      // Setup send buttons in special "flag" table rows.
      $('tr[data-flag]').each(function armSendFlagBtns() {
        const container = $(this);
        $('.switch', this).on('click', function send() {
          sendFlag(
            CONNECTION, container.data('flag'),
            $(this).hasClass('on'),
          );
        });
      });

      armSetterBtns(CONNECTION);
      $('#mod_demod_settings').on(
        'click',
        () => sendModDemodSettings(CONNECTION),
      );

      $('input[type=button][data-method][data-arguments]')
        .each(function armMethodCallBtn() {
          const button = $(this);
          button.on('click', () => {
            const commandName = button.data('method');
            const args = button.data('arguments');
            callRemoteMethod(CONNECTION, commandName, args);
          });
        });
      const advancedBtns = document.querySelectorAll('input[type=button][data-method][data-arguments-source]');
      for (const btn of advancedBtns) {
        btn.addEventListener('click', () => {
          const command = btn.dataset.method;
          const src = document.querySelectorAll(btn.dataset.argumentsSource);
          const args = src.value;
          callRemoteMethod(CONNECTION, command, args);
        });
      }

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
          if (!document.getElementById('allow_permanent_unlock').checked) {
            if (this.type === 'button') {
              sswitch.prop('checked', false);
              sswitch.trigger('change');
            }
          }
        });
      });
      setupRunlevelGauges();
    }
  });
}());
