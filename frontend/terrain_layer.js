/*
 * Terrain layer for the RealTimers dashboard: the GIS half of the physics chain.
 *
 *   Valley HAND      height above the nearest major (Strahler 3+) stream
 *   Streams          stream links coloured and sized by Strahler order
 *   Micro-catchments one per stream link -- the future SWMM subcatchments
 *
 * Adds a small "Layers" card with toggles, including the BBMP drain network.
 * Everything reads from /v1/terrain/*, so the card also states what the
 * terrain was built from and whether the depth model is using it.
 */
const TerrainLayer = (() => {
  const BLUES = ['#9ecae1', '#6baed6', '#4292c6', '#2171b5', '#08519c', '#08306b'];

  async function attach(map, { drains } = {}) {
    let status;
    try {
      status = await (await fetch('/v1/terrain/status')).json();
    } catch (err) {
      console.warn('terrain status unavailable', err);
      return;
    }
    if (!status || !status.built) return;

    const [W, S, E, N] = status.bbox;
    const below = (id) => (map.getLayer(id) ? id : undefined);

    // Valley HAND overlay, under everything that carries water or depth.
    map.addSource('hand', {
      type: 'image', url: status.hand_png,
      coordinates: [[W, N], [E, N], [E, S], [W, S]],
    });
    map.addLayer({
      id: 'hand', type: 'raster', source: 'hand',
      paint: { 'raster-opacity': 0.8, 'raster-fade-duration': 0 },
      layout: { visibility: 'none' },
    }, below('roads'));

    // Streams by Strahler order. Order 1 is left out by default: it is mostly
    // hillslope flow paths and clutters the view.
    map.addSource('streams', { type: 'geojson', data: '/v1/terrain/streams?min_order=2' });
    map.addLayer({
      id: 'streams', type: 'line', source: 'streams',
      layout: { visibility: 'none', 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': ['match', ['get', 'strahler'],
          1, BLUES[0], 2, BLUES[1], 3, BLUES[2], 4, BLUES[3], 5, BLUES[4], BLUES[5]],
        'line-width': ['interpolate', ['linear'], ['get', 'strahler'], 2, 0.9, 6, 4.5],
      },
    }, below('flood'));

    // Micro-catchments load only when first switched on -- the file is large.
    let catchmentsLoaded = false;
    function ensureCatchments() {
      if (catchmentsLoaded) return;
      catchmentsLoaded = true;
      map.addSource('catchments', { type: 'geojson', data: '/v1/terrain/catchments' });
      map.addLayer({
        id: 'catchments-fill', type: 'fill', source: 'catchments',
        paint: { 'fill-color': '#2171b5', 'fill-opacity': 0.0 },
      }, below('flood'));
      map.addLayer({
        id: 'catchments', type: 'line', source: 'catchments',
        paint: { 'line-color': '#4a5c68', 'line-width': 0.7, 'line-opacity': 0.7 },
      }, below('flood'));
      map.on('click', 'catchments-fill', (ev) => {
        const p = ev.features[0].properties;
        popup(ev.lngLat,
          `<b>Micro-catchment ${p.id}</b>` +
          row('Area', `${Number(p.area_ha).toFixed(1)} ha`) +
          row('Drains to', `${p.link} · Strahler ${p.strahler}`) +
          row('Mean valley HAND', `${Number(p.mean_hand_m).toFixed(1)} m`) +
          row('Impervious', `${Math.round(p.mean_imperv * 100)}%`) +
          row('Mean slope', `${Number(p.mean_slope_deg).toFixed(1)}°`));
      });
    }

    map.on('click', 'streams', (ev) => {
      const p = ev.features[0].properties;
      popup(ev.lngLat,
        `<b>Stream link ${p.id}</b>` +
        row('Strahler order', p.strahler) +
        row('Contributing area', `${Number(p.area_ha).toFixed(0)} ha`) +
        row('Gradient', `${(Number(p.gradient) * 100).toFixed(2)}%`) +
        row('On a BBMP drain', `${Math.round(p.on_drain_share * 100)}% of length`) +
        row('Flows into', p.downstream && p.downstream !== 'null' ? p.downstream : 'leaves the area'));
    });
    for (const id of ['streams']) {
      map.on('mouseenter', id, () => { map.getCanvas().style.cursor = 'pointer'; });
      map.on('mouseleave', id, () => { map.getCanvas().style.cursor = ''; });
    }

    const drainCtl = drains ? await drains : null;
    card(map, status, {
      drains: drainCtl ? (on) => drainCtl.toggle(on) : null,
      streams: (on) => map.setLayoutProperty('streams', 'visibility', on ? 'visible' : 'none'),
      catchments: (on) => {
        if (on) ensureCatchments();
        const v = on ? 'visible' : 'none';
        for (const id of ['catchments', 'catchments-fill']) {
          if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', v);
        }
      },
      hand: (on) => map.setLayoutProperty('hand', 'visibility', on ? 'visible' : 'none'),
    });
  }

  function row(k, v) {
    return `<div style="display:flex;justify-content:space-between;gap:14px;` +
      `font:12px/1.7 system-ui"><span style="color:#5a6b78">${k}</span><span>${v}</span></div>`;
  }

  function popup(lngLat, html) {
    new maplibregl.Popup({ maxWidth: '280px' }).setLngLat(lngLat)
      .setHTML(`<div style="font:13px/1.4 system-ui">${html}</div>`).addTo(window.__rtmap);
  }

  function card(map, status, toggles) {
    window.__rtmap = map;
    const el = document.createElement('section');
    el.className = 'float';
    el.setAttribute('aria-label', 'Map layers');
    el.style.cssText = 'left:232px;top:268px;padding:12px 14px;width:208px;box-sizing:border-box;';

    const items = [
      ['drains', 'BBMP drain network', true],
      ['streams', 'Streams by Strahler order', false],
      ['catchments', 'Micro-catchments', false],
      ['hand', 'Valley HAND', false],
    ].filter(([k]) => toggles[k]);

    el.innerHTML =
      `<h2 style="margin:0 0 8px;font:600 15px/1 var(--cond, system-ui);letter-spacing:.02em">Layers</h2>` +
      items.map(([k, label, on]) =>
        `<label style="display:flex;align-items:center;gap:8px;font-size:13px;line-height:1.9;cursor:pointer">` +
        `<input type="checkbox" data-k="${k}" ${on ? 'checked' : ''} style="margin:0">${label}</label>`).join('') +
      `<div id="hand-key" style="display:none;margin-top:6px">` +
      `<div style="height:8px;border-radius:2px;background:linear-gradient(90deg,#08306b,#2171b5,#6baed6,#c6dbef,transparent)"></div>` +
      `<div style="display:flex;justify-content:space-between;font-size:11px;color:#5a6b78"><span>0 m</span><span>5</span><span>14 m+</span></div></div>` +
      `<p style="margin:10px 0 0;font-size:11.5px;line-height:1.45;color:#5a6b78">` +
      `${status.stream_links.toLocaleString()} stream links · ${status.micro_catchments.toLocaleString()} micro-catchments. ` +
      `Terrain from GLO-30, ${status.cell_m} m grid. ` +
      `Depth model is using <b>${status.depth_model_terrain === 'real' ? 'real' : 'synthetic'}</b> terrain.</p>`;

    el.addEventListener('change', (ev) => {
      const k = ev.target.dataset.k;
      if (!k) return;
      toggles[k](ev.target.checked);
      if (k === 'hand') el.querySelector('#hand-key').style.display = ev.target.checked ? 'block' : 'none';
    });
    document.body.appendChild(el);
  }

  return { attach };
})();
