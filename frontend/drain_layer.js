/*
 * Drain network layer for the RealTimers dashboard.
 *
 * In frontend/index.html, after the map is created:
 *
 *     <script src="drain_layer.js"></script>
 *     ...
 *     map.on('load', () => { DrainLayer.attach(map); });
 *
 * Renders BBMP primary, secondary and tertiary drains, with a provenance
 * chip that reports what the source actually contains. The chip is not
 * decoration: it is the answer to "where did this network come from",
 * rendered from the API rather than remembered.
 */
const DrainLayer = (() => {
  const SRC = 'swd';
  const STYLE = {
    Primary: { color: '#4D9FE0', width: [2.2, 5.5] },
    Secondary: { color: '#3E7FA8', width: [1.4, 3.4] },
    Tertiary: { color: '#33607D', width: [0.7, 1.8] },
  };

  let visible = true;

  async function attach(map, { api = '' } = {}) {
    let geojson;
    try {
      const res = await fetch(`${api}/v1/drains`);
      if (!res.ok) throw new Error(await res.text());
      geojson = await res.json();
    } catch (err) {
      console.warn('drain network unavailable:', err);
      chip(map, null);
      return;
    }

    map.addSource(SRC, { type: 'geojson', data: geojson });

    // Draw tertiary first so primary trunks sit on top.
    for (const kind of ['Tertiary', 'Secondary', 'Primary']) {
      const s = STYLE[kind];
      map.addLayer({
        id: `swd-${kind.toLowerCase()}`,
        type: 'line',
        source: SRC,
        filter: ['==', ['get', 'type'], kind],
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: {
          'line-color': s.color,
          'line-opacity': 0.85,
          'line-width': [
            'interpolate', ['linear'], ['zoom'],
            11, s.width[0],
            16, s.width[1],
          ],
        },
      });
    }

    const ids = ['swd-primary', 'swd-secondary', 'swd-tertiary'];

    map.on('click', (ev) => {
      const hit = map.queryRenderedFeatures(ev.point, { layers: ids })[0];
      if (!hit) return;
      const p = hit.properties;
      const km = (Number(p.length_m) / 1000).toFixed(2);
      new maplibregl.Popup({ closeButton: true, maxWidth: '260px' })
        .setLngLat(ev.lngLat)
        .setHTML(
          `<div style="font:600 13px/1.3 system-ui">${p.ref_name || p.type + ' drain'}</div>` +
          `<div style="font:11px/1.6 ui-monospace,monospace;color:#5a6b78;margin-top:4px">` +
          `${p.id} · ${p.type} · ${km} km<br>` +
          `BBMP id ${p.source_id}</div>` +
          `<div style="font:11px/1.4 system-ui;color:#8a5a12;background:#fdf3e0;` +
          `border-radius:4px;padding:6px 7px;margin-top:7px">` +
          `No diameter, invert or slope in the published data. ` +
          `Hydraulic values are estimated.</div>`
        )
        .addTo(map);
    });

    for (const id of ids) {
      map.on('mouseenter', id, () => { map.getCanvas().style.cursor = 'pointer'; });
      map.on('mouseleave', id, () => { map.getCanvas().style.cursor = ''; });
    }

    try {
      const status = await (await fetch(`${api}/v1/drains/status`)).json();
      chip(map, status);
    } catch (err) {
      chip(map, null);
    }

    return {
      toggle(on) {
        visible = on === undefined ? !visible : on;
        for (const id of ids) {
          map.setLayoutProperty(id, 'visibility', visible ? 'visible' : 'none');
        }
        return visible;
      },
    };
  }

  function chip(map, status) {
    const el = document.createElement('div');
    el.style.cssText =
      'position:absolute;left:16px;top:150px;z-index:6;background:#151C23;color:#E9EEF2;' +
      'border:1px solid #28323C;border-radius:4px;padding:10px 12px;width:312px;' +
      'box-sizing:border-box;' +
      'font:11px/1.55 ui-monospace,SFMono-Regular,monospace';

    if (!status || !status.loaded) {
      el.innerHTML =
        '<b style="color:#F2A33A">DRAIN NETWORK NOT LOADED</b><br>' +
        'Run tools/ingest_drains.py on the OpenCity KML.';
    } else {
      const c = status.counts || {};
      el.innerHTML =
        `<b>BBMP SWD NETWORK</b><br>` +
        `${(c.Primary || 0).toLocaleString()} primary · ` +
        `${(c.Secondary || 0).toLocaleString()} secondary · ` +
        `${(c.Tertiary || 0).toLocaleString()} tertiary<br>` +
        `${status.total_km} km in the pilot area<br>` +
        `<span style="color:#9AA8B4">${status.attribution}</span><br>` +
        `<span style="color:#F2A33A">geometry only — ` +
        `${status.derived_fields.length} hydraulic fields estimated</span>`;
    }
    map.getContainer().appendChild(el);
  }

  return { attach };
})();
