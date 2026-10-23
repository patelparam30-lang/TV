/* East Lansing forecast. ES5 runtime, bounded HTTPS requests, no API key. */
(function () {
  'use strict';
  var PREFS = 'cleanframe.weather.v1', CACHE = 'cleanframe.weather.cache.v1';
  var INTERVAL = 15 * 60000, STALE = 60 * 60000, EXPIRE = 6 * 60 * 60000;
  var URL = 'https://api.open-meteo.com/v1/forecast?latitude=42.737&longitude=-84.484'
    + '&current=temperature_2m,apparent_temperature,is_day,weather_code'
    + '&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max'
    + '&temperature_unit=celsius&timezone=America%2FDetroit&timeformat=unixtime&forecast_days=1';
  var enabled = true, data = null, loading = false, error = '', saveError = '';
  var callback = function () {}, timer = 0, request = null, generation = 0, lastAttempt = 0;
  var CONDITIONS = {
    0: ['Clear skies', 'clear'], 1: ['Mostly clear', 'clear'], 2: ['Partly cloudy', 'cloud'], 3: ['Overcast skies', 'cloud'],
    45: ['Foggy conditions', 'fog'], 48: ['Freezing fog', 'fog'],
    51: ['Light drizzle', 'rain'], 53: ['Drizzle', 'rain'], 55: ['Steady drizzle', 'rain'],
    56: ['Light freezing drizzle', 'rain'], 57: ['Freezing drizzle', 'rain'],
    61: ['Light rain', 'rain'], 63: ['Rain', 'rain'], 65: ['Heavy rain', 'rain'],
    66: ['Light freezing rain', 'rain'], 67: ['Freezing rain', 'rain'],
    71: ['Light snow', 'snow'], 73: ['Snow', 'snow'], 75: ['Heavy snow', 'snow'], 77: ['Snow grains', 'snow'],
    80: ['Light rain showers', 'rain'], 81: ['Rain showers', 'rain'], 82: ['Heavy rain showers', 'rain'],
    85: ['Light snow showers', 'snow'], 86: ['Heavy snow showers', 'snow'],
    95: ['Thunderstorms', 'storm'], 96: ['Thunderstorms with hail', 'storm'], 99: ['Thunderstorms with heavy hail', 'storm']
  };
  function finite(n, min, max) { return typeof n === 'number' && isFinite(n) && n >= min && n <= max; }
  function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
  function read(key) { try { return JSON.parse(localStorage.getItem(key)); } catch (e) { return null; } }
  function valid(d) {
    return d && d.city === 'east-lansing-mi' && finite(d.time, 1, Date.now() + 15 * 60000)
      && finite(d.temp, -100, 70) && finite(d.feels, -120, 100) && finite(d.code, 0, 99) && CONDITIONS.hasOwnProperty(d.code)
      && (d.day === 0 || d.day === 1) && finite(d.high, -100, 70) && finite(d.low, -100, 70) && d.high >= d.low
      && finite(d.rain, 0, 100) && finite(d.dayStart, 1, Date.now() + 24 * 60 * 60000);
  }
  var prefs = read(PREFS), cached = read(CACHE);
  if (prefs && typeof prefs.enabled === 'boolean') enabled = prefs.enabled;
  if (valid(cached) && Date.now() - cached.time < EXPIRE) data = cached;

  function pair(c) { return Math.round(c * 9 / 5 + 32) + '°F / ' + Math.round(c) + '°C'; }
  function ageText() {
    var minutes = data ? Math.max(0, Math.floor((Date.now() - data.time) / 60000)) : 0;
    return minutes < 1 ? 'Just updated' : minutes < 60 ? 'Updated ' + minutes + ' min ago' : 'Updated ' + Math.floor(minutes / 60) + ' hr ago';
  }
  function state() {
    var age = data ? Math.max(0, Date.now() - data.time) : Infinity;
    return { enabled: enabled, loading: loading, error: error, saveError: saveError, data: data,
      stale: age > STALE, expired: age >= EXPIRE, age: age };
  }
  function description() {
    if (!data) return '';
    var text = CONDITIONS[data.code][0] + (data.day ? ' right now.' : ' tonight.');
    return text + ' Feels like ' + pair(data.feels) + '.';
  }
  function glyph(kind, day) {
    var paths = '', sun = '<circle cx="32" cy="28" r="10" fill="#ffd78d" stroke="none"/><path d="M32 10v-4m0 44v-4M14 28h-4m44 0h-4M19 15l-3-3m32 32-3-3m0-26 3-3M19 41l-3 3" stroke="#ffd78d"/>';
    var cloud = '<path d="M18 46a10 10 0 0 1-1-20 14 14 0 0 1 27-3 11.5 11.5 0 1 1 2 23Z" fill="#eef3f7" stroke="none"/>';
    if (kind === 'clear') paths = day ? sun : '<path d="M45 41A20 20 0 0 1 23 11a21 21 0 1 0 22 30Z" fill="#dce8fc" stroke="none"/>';
    else if (kind === 'cloud') paths = (data && data.code === 2 && day ? '<g transform="translate(8 -5) scale(.8)">' + sun + '</g>' : '') + cloud;
    else if (kind === 'fog') paths = '<path d="M12 24h40M8 34h48M14 44h36" stroke="#dce8ee"/>';
    else {
      paths = '<g transform="translate(0 -6)">' + cloud + '</g>';
      if (kind === 'storm') paths += '<path d="m35 38-9 13h8l-5 11 15-16h-9l5-8Z" fill="#ffd78d" stroke="none"/>';
      else if (kind === 'snow') paths += '<path d="M18 48v8m-4-4h8m10-4v8m-4-4h8m10-4v8m-4-4h8" stroke="#e1f3ff" stroke-width="2.5"/>';
      else paths += '<path d="m21 46-3 9m16-9-3 9m16-9-3 9" stroke="#9dcfff"/>';
    }
    return '<svg class="weather-symbol" viewBox="0 0 64 64" fill="none" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + paths + '</svg>';
  }
  function html() {
    var s = state(), content, label = '<div class="weather-city">East Lansing<span class="weather-location-dot" aria-hidden="true"></span></div>';
    if (data && !s.expired) {
      content = '<div class="weather-now">' + glyph(CONDITIONS[data.code][1], data.day)
        + '<div class="weather-temperature"><span class="weather-fahrenheit">' + Math.round(data.temp * 9 / 5 + 32) + '<small>°F</small></span>'
        + '<span class="weather-celsius">' + Math.round(data.temp) + '°C</span></div></div>'
        + '<p class="weather-description">' + (s.stale ? 'Last known: ' : '') + esc(description()) + '</p>'
        + '<p class="weather-range">' + (Date.now() - data.dayStart < 24 * 60 * 60000 ? 'Today' : 'Last forecast') + ' · ' + pair(data.low) + ' to ' + pair(data.high) + '</p>';
      content += '<p class="weather-credit">Open-Meteo · ' + esc(ageText()) + (error ? ' · Offline' : '') + '</p>';
    } else {
      content = '<div class="weather-empty-symbol" aria-hidden="true">' + glyph('cloud', 0) + '</div>'
        + '<p class="weather-unavailable">' + (loading ? 'Checking the sky…' : 'Weather unavailable') + '</p>'
        + '<p class="weather-description">' + (loading ? 'Your East Lansing forecast is on its way.' : 'The clock and your apps are ready. Try refreshing in Settings → Weather.') + '</p>'
        + '<p class="weather-credit">Forecasts by Open-Meteo</p>';
    }
    return label + content;
  }
  function statusText() {
    if (saveError) return saveError;
    if (!enabled) return 'Weather is hidden. Your clock and apps still work offline.';
    if (loading) return 'Updating the East Lansing forecast…';
    if (error) return data && !state().expired ? 'Couldn’t update. ' + ageText() + '; the previous forecast is labelled on Home.' : 'Couldn’t reach the forecast service. Check the connection, then choose Refresh forecast.';
    return data && !state().expired ? description() + ' ' + ageText() + '. Forecast data by Open-Meteo (CC BY 4.0).' : 'Choose Refresh forecast to try again.';
  }
  function changed() { callback(); }
  function schedule() {
    clearTimeout(timer);
    if (enabled && !document.hidden) timer = setTimeout(function () { changed(); refresh(false); }, INTERVAL);
  }
  function parse(body) {
    var c = body && body.current, d = body && body.daily, units = body && body.current_units;
    if (!c || !d || !units || units.temperature_2m !== '°C' || !Array.isArray(d.time) || !Array.isArray(d.temperature_2m_max) || !Array.isArray(d.temperature_2m_min) || !Array.isArray(d.precipitation_probability_max)) return null;
    var result = { city: 'east-lansing-mi', time: c.time * 1000, temp: c.temperature_2m, feels: c.apparent_temperature,
      code: c.weather_code, day: c.is_day, high: d.temperature_2m_max[0], low: d.temperature_2m_min[0], rain: d.precipitation_probability_max[0], dayStart: d.time[0] * 1000 };
    return valid(result) && Date.now() - result.time < EXPIRE ? result : null;
  }
  function refresh(force) {
    if (!enabled || document.hidden || loading) return;
    if (!force && Date.now() - lastAttempt < INTERVAL) { schedule(); return; }
    var token = ++generation, xhr = new XMLHttpRequest(), ended = false;
    lastAttempt = Date.now(); loading = true; error = ''; request = xhr;
    function finish(value) {
      if (ended || token !== generation) return;
      ended = true; loading = false; request = null;
      if (value) {
        data = value; error = '';
        try { localStorage.setItem(CACHE, JSON.stringify(value)); } catch (e) { /* A forecast remains usable without cache storage. */ }
      } else error = 'Forecast unavailable';
      changed(); schedule();
    }
    try {
      xhr.open('GET', URL, true); xhr.timeout = 12000;
      xhr.onload = function () {
        var value = null;
        if (xhr.status === 200) { try { value = parse(JSON.parse(xhr.responseText)); } catch (e) { /* Invalid responses never replace the last forecast. */ } }
        finish(value);
      };
      xhr.onerror = xhr.ontimeout = function () { finish(null); };
      xhr.send();
    } catch (e) { finish(null); }
    changed();
  }
  function cancel() {
    ++generation;
    if (request) { request.abort(); request = null; }
    loading = false; clearTimeout(timer);
  }
  function toggle() {
    try { localStorage.setItem(PREFS, JSON.stringify({ enabled: !enabled })); }
    catch (e) { saveError = 'Couldn’t save this change. Your weather setting is unchanged. Try again.'; changed(); return false; }
    saveError = ''; enabled = !enabled;
    if (!enabled) cancel();
    else refresh(true);
    changed(); return true;
  }
  function start(onChange) {
    callback = onChange; changed();
    if (enabled && !document.hidden) refresh(false);
    document.addEventListener('visibilitychange', function () {
      if (document.hidden) cancel();
      else { changed(); refresh(false); }
    });
    window.addEventListener('focus', function () { changed(); refresh(false); });
  }
  window.CleanFrameWeather = { start: start, state: state, html: html, refresh: refresh, toggle: toggle, statusText: statusText };
}());
