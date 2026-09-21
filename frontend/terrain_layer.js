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

    // ---- BBMP flood spots: the points the terrain was validated against ----
    const SPOTS = [
      ['flood_vulnerable_locations', '#b2182b', 'Vulnerable location'],
      ['flood_prone_locations', '#ef8a62', 'Flood-prone location'],
      ['lowlying_locations', '#7b3294', 'Low-lying location'],
    ];
    let spotsLoaded = false;
    function ensureSpots() {
      if (spotsLoaded) return;
      spotsLoaded = true;
      for (const [slug, colour, label] of SPOTS) {
        map.addSource(`spots-${slug}`, { type: 'geojson', data: `/v1/opencity/bengaluru/${slug}` });
        map.addLayer({
          id: `spots-${slug}`, type: 'circle', source: `spots-${slug}`,
          paint: {
            'circle-radius': ['interpolate', ['linear'], ['zoom'], 10, 3, 15, 7],
            'circle-color': colour, 'circle-stroke-color': '#ffffff', 'circle-stroke-width': 1.2,
          },
        });
        map.on('click', `spots-${slug}`, (ev) => {
          const q = ev.features[0].properties;
          popup(ev.lngLat, `<b>${label}</b>` +
            (q.LocationName ? row('Place', q.LocationName) : '') +
            (q.WARD_NAME ? row('Ward', `${q.WARD_NAME} (${q.WARDNO})`) : '') +
            (q.ZONE ? row('Zone', q.ZONE) : '') +
            `<div style="font:11px/1.4 system-ui;color:#5a6b78;margin-top:6px">Listed by BBMP; used to test the terrain layer</div>`);
        });
      }
    }

    // ---- BBMP lakes: the outfalls burned into the terrain ----
    let lakesLoaded = false;
    function ensureLakes() {
      if (lakesLoaded) return;
      lakesLoaded = true;
      map.addSource('lakes', { type: 'geojson', data: '/v1/opencity/bengaluru/lakes_streams?geom=Polygon' });
      map.addLayer({ id: 'lakes-fill', type: 'fill', source: 'lakes',
        paint: { 'fill-color': '#6baed6', 'fill-opacity': 0.45 } }, below('flood'));
      map.addLayer({ id: 'lakes-line', type: 'line', source: 'lakes',
        paint: { 'line-color': '#2171b5', 'line-width': 1 } }, below('flood'));
      map.on('click', 'lakes-fill', (ev) => {
        const q = ev.features[0].properties;
        popup(ev.lngLat, `<b>${q.Name_of_th || 'Lake'}</b>` +
          (q.Valley ? row('Valley', q.Valley) : '') +
          (q.Area ? row('Area, as published', q.Area) : '') +
          (q.Ward_Name ? row('Ward', q.Ward_Name) : ''));
      });
    }

    // ---- GBA corporations and zones: who operates each place ----
    let adminLoaded = false;
    function ensureAdmin() {
      if (adminLoaded) return;
      adminLoaded = true;
      map.addSource('zones', { type: 'geojson', data: '/v1/opencity/bengaluru/zones' });
      map.addLayer({ id: 'zones', type: 'line', source: 'zones',
        paint: { 'line-color': '#7f8c8d', 'line-width': 1 } });
      map.addSource('corporations', { type: 'geojson', data: '/v1/opencity/bengaluru/corporations' });
      map.addLayer({ id: 'corporations', type: 'line', source: 'corporations',
        paint: { 'line-color': '#34495e', 'line-width': 2.2, 'line-dasharray': [4, 2] } });
    }

    const setVis = (ids, on) => ids.forEach((id) => {
      if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', on ? 'visible' : 'none');
    });

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
      spots: (on) => { if (on) ensureSpots(); setVis(SPOTS.map(([sl]) => `spots-${sl}`), on); },
      lakes: (on) => { if (on) ensureLakes(); setVis(['lakes-fill', 'lakes-line'], on); },
      admin: (on) => { if (on) ensureAdmin(); setVis(['corporations', 'zones'], on); },
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

  function injectCss() {
    if (document.getElementById('rt-layers-css')) return;
    const st = document.createElement('style');
    st.id = 'rt-layers-css';
    st.textContent = `
      .rt-layers { left: 232px; top: 268px; width: 228px; padding: 0; box-sizing: border-box;
        display: flex; flex-direction: column; max-height: calc(100vh - 268px - 108px); }
      .rt-layers > button { all: unset; box-sizing: border-box; width: 100%; padding: 10px 14px;
        cursor: pointer; display: flex; justify-content: space-between; align-items: center;
        font: 600 15px/1 var(--cond, system-ui); letter-spacing: .02em; }
      .rt-layers > button:focus-visible { outline: 2px solid #2171b5; outline-offset: -2px; }
      .rt-layers .rt-body { padding: 0 14px 12px; overflow-y: auto; }
      .rt-layers.collapsed .rt-body { display: none; }
      .rt-layers .rt-chev { transition: transform .15s; }
      .rt-layers.collapsed .rt-chev { transform: rotate(-90deg); }
      .rt-layers .rt-note { margin: 10px 0 0; font-size: 11.5px; line-height: 1.45; color: #5a6b78; }
      /* short laptop screens: sit beside the title card instead of under it */
      @media (min-width: 861px) and (max-height: 760px) {
        .rt-layers { top: 16px; left: 372px; max-height: calc(100vh - 124px); } }
      /* phone layout: top-right, clear of the depth scale and the bottom panel */
      @media (max-width: 860px) {
        .rt-layers { left: auto; right: 16px; top: 96px; width: 210px; max-height: calc(60vh - 224px); } }
    `;
    document.head.appendChild(st);
  }

  function card(map, status, toggles) {
    window.__rtmap = map;
    injectCss();
    const el = document.createElement('section');
    el.className = 'float rt-layers';
    el.setAttribute('aria-label', 'Map layers');
    // Start open only where there is room; the header button toggles it.
    const roomy = window.innerWidth > 860 && window.innerHeight > 760;
    if (!roomy) el.classList.add('collapsed');

    const items = [
      ['drains', 'BBMP drain network', true],
      ['streams', 'Streams by Strahler order', false],
      ['catchments', 'Micro-catchments', false],
      ['hand', 'Valley HAND', false],
      ['spots', 'BBMP flood spots', false],
      ['lakes', 'Lakes', false],
      ['admin', 'Corporations and zones', false],
    ].filter(([k]) => toggles[k]);

    const v = status.validation;
    el.innerHTML =
      `<button type="button" aria-expanded="${roomy}"><span>Layers</span><span class="rt-chev" aria-hidden="true">&#9662;</span></button>` +
      `<div class="rt-body">` +
      items.map(([k, label, on]) =>
        `<label style="display:flex;align-items:center;gap:8px;font-size:13px;line-height:1.9;cursor:pointer">` +
        `<input type="checkbox" data-k="${k}" ${on ? 'checked' : ''} style="margin:0">${label}</label>`).join('') +
      `<div id="hand-key" style="display:none;margin-top:6px">` +
      `<div style="height:8px;border-radius:2px;background:linear-gradient(90deg,#08306b,#2171b5,#6baed6,#c6dbef,transparent)"></div>` +
      `<div style="display:flex;justify-content:space-between;font-size:11px;color:#5a6b78"><span>0 m</span><span>5</span><span>14 m+</span></div></div>` +
      `<div id="spots-key" style="display:none;margin-top:6px;font-size:11.5px;line-height:1.7">` +
      [['#b2182b', 'vulnerable'], ['#ef8a62', 'flood-prone'], ['#7b3294', 'low-lying']].map(([c, t]) =>
        `<span style="display:inline-flex;align-items:center;gap:4px;margin-right:8px">` +
        `<span style="width:9px;height:9px;border-radius:50%;background:${c}"></span>${t}</span>`).join('') +
      `</div>` +
      (v ? `<p class="rt-note" style="color:inherit"><b>Checked against ${v.n_in_pilot} BBMP flood spots:</b> ` +
           `AUC ${v.auc_vs_built_up.toFixed(2)}. The lowest-lying 20% of built-up land holds ` +
           `${Math.round(v.lowest20_holds_share_of_spots * 100)}% of them.</p>` : '') +
      `<p class="rt-note" id="rt-drains-note"></p>` +
      `<p class="rt-note">${status.stream_links.toLocaleString()} stream links · ` +
      `${status.micro_catchments.toLocaleString()} micro-catchments. Terrain from GLO-30, ${status.cell_m} m grid. ` +
      `Depth model is using <b>${status.depth_model_terrain === 'real' ? 'real' : 'synthetic'}</b> terrain.</p>` +
      `</div>`;

    const btn = el.querySelector('button');
    btn.addEventListener('click', () => {
      const open = el.classList.toggle('collapsed') === false;
      btn.setAttribute('aria-expanded', String(open));
    });
    el.addEventListener('change', (ev) => {
      const k = ev.target.dataset.k;
      if (!k) return;
      toggles[k](ev.target.checked);
      if (k === 'hand') el.querySelector('#hand-key').style.display = ev.target.checked ? 'block' : 'none';
      if (k === 'spots') el.querySelector('#spots-key').style.display = ev.target.checked ? 'block' : 'none';
    });
    document.body.appendChild(el);

    // Drain provenance lives here now, instead of a separate floating chip.
    fetch('/v1/drains/status').then((r) => r.json()).then((d) => {
      if (!d || !d.loaded) return;
      const c = d.counts || {};
      el.querySelector('#rt-drains-note').innerHTML =
        `<b>Drains:</b> ${(c.Primary || 0).toLocaleString()} primary · ${(c.Secondary || 0).toLocaleString()} secondary · ` +
        `${(c.Tertiary || 0).toLocaleString()} tertiary, ${d.total_km} km, from BBMP via OpenCity (KSRSAC). ` +
        `Geometry only &mdash; ${d.derived_fields.length} hydraulic fields estimated.`;
    }).catch(() => {});
  }

  return { attach };
})();
