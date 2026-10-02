(() => {
  'use strict';
  const $=id=>document.getElementById(id), auth=$('explorer').dataset.authenticated==='true';
  const start=$('query-start'),end=$('query-end'),station=$('query-station'),status=$('query-status');
  const now=new Date();end.value=now.toISOString().slice(0,16);start.value=new Date(now.getTime()-7*86400000+60000).toISOString().slice(0,16);
  end.max=now.toISOString().slice(0,16);if(!auth) start.min=start.value;
  const period=$('query-period');
  function updatePeriod(){
    const automatic=period.value==='last7';start.disabled=automatic;end.disabled=automatic;
    const current=new Date();end.max=current.toISOString().slice(0,16);
    if(!auth)start.min=new Date(current.getTime()-7*86400000+60000).toISOString().slice(0,16);
    if(automatic){start.value=new Date(current.getTime()-7*86400000+60000).toISOString().slice(0,16);end.value=current.toISOString().slice(0,16);}
  }
  period.addEventListener('change',updatePeriod);updatePeriod();
  let stations=[],map=null,markers=null,mapFitted=false,result=null,lastQuery=null,busy=false;
  const signals=new Map();
  const signalColors={recent:'#15803d',corrupt:'#c2410c',week:'#d39100',historical:'#dc2626',empty:'#7f1d1d',unknown:'#64748b'};
  const signalLabels={recent:'Datos decodificados en las últimas 24 horas',corrupt:'Recibe transmisiones, pero el contenido reciente no se puede decodificar',week:'Datos de 1 a 7 días; sin mediciones en 24 h',historical:'Con histórico; sin mediciones en los últimos 7 días',empty:'Sin mediciones asociadas a la clave y DCP configurados',unknown:'Sin verificar: vínculo no disponible o consulta fallida'};
  const signalShort={recent:'Datos ≤24 h',corrupt:'Transmite · contenido inválido',week:'1–7 días',historical:'Solo histórico',empty:'Sin mediciones asociadas',unknown:'Sin verificar'};
  const show=(message,error=false)=>{status.textContent=message;status.className=error?'error':'';};
  function populateMap() {
    if(!map||!markers)return;markers.clearLayers();const points=[];
    for(const s of stations) {
      const state=signals.get(s.id)||'unknown';if($('map-filter').value!=='all'&&$('map-filter').value!==state)continue;
      if(s.latitude==null||s.longitude==null||Math.abs(s.latitude)>90||Math.abs(s.longitude)>180)continue;
      const box=document.createElement('div'),title=document.createElement('strong'),button=document.createElement('button'),detail=document.createElement('p');
      detail.textContent=signalLabels[state];detail.className='popup-status';
      title.textContent=s.name+' · '+s.code;button.textContent='Consultar estación';button.type='button';button.addEventListener('click',()=>{station.value=s.id;map.closePopup();$('query-form').scrollIntoView({behavior:'smooth'});});
      box.append(title,detail,button);
      const tooltip=document.createElement('span');tooltip.textContent=s.name+' · '+signalShort[state];
      L.circleMarker([s.latitude,s.longitude],{radius:state==='empty'?6:5,weight:1.5,color:'#ffffff',fillColor:signalColors[state],fillOpacity:.95}).bindPopup(box).bindTooltip(tooltip).addTo(markers);points.push([s.latitude,s.longitude]);
    }
    if(points.length&&!mapFitted){map.fitBounds(points,{padding:[20,20],maxZoom:10});mapFitted=true;}
    $('map-status').textContent=points.length+' estaciones en el mapa · '+stations.length+' en catálogo';
  }
  function refreshSignals(){
    for(const state of Object.keys(signalColors))$('count-'+state).textContent=stations.filter(s=>(signals.get(s.id)||'unknown')===state).length;
    for(const option of station.options){const s=stations.find(s=>s.id===option.value);if(s)option.textContent=s.name+' · '+s.code+' · '+signalShort[signals.get(s.id)||'unknown'];}
    populateMap();
  }
  $('map-filter').addEventListener('change',populateMap);
  function initializeMap(){
    if(map)return;if(!window.L){$('map-status').textContent='No se pudo cargar el mapa; utiliza el selector de estaciones.';return;}
    map=L.map('station-map').setView([23.5,-102],5);
    markers=L.layerGroup().addTo(map);
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'}).addTo(map).on('tileerror',()=>{$('map-status').textContent='El mapa base no está disponible. Las estaciones siguen disponibles en el selector.';});
    populateMap();
  }
  initializeMap();
  fetch('/Explore/Stations').then(async r=>{if(!r.ok)throw Error();return r.json();}).then(rows=>{
    stations=rows;for(const s of rows){const option=document.createElement('option');option.value=s.id;option.textContent=s.name+' · '+s.code;station.append(option);}
    $('map-status').textContent=rows.length+' estaciones disponibles.';refreshSignals();
  }).catch(()=>{$('map-status').textContent='No fue posible cargar el catálogo. Recarga la página para reintentar.';});
  fetch('/Explore/Availability').then(async r=>{if(!r.ok)throw Error();return r.json();}).then(data=>{
    for(const s of data.stations)signals.set(s.stationId,s.state in signalColors?s.state:'unknown');
    $('signal-status').textContent='Transmisiones y mediciones verificadas: '+new Date(data.checkedAt).toLocaleTimeString()+' · ventanas de 24 h / 7 días';refreshSignals();
  }).catch(()=>{$('signal-status').textContent='No se pudo verificar el semáforo. Gris no significa sin datos.';});
  function params(){
    const query=new URLSearchParams({stationId:station.value,product:$('query-product').value});
    // Omit dates in live mode: the server computes its current seven-day window.
    if(period.value!=='last7'){query.set('start',start.value+':00Z');query.set('end',end.value+':00Z');}
    return query;
  }
  $('query-form').addEventListener('submit',async e=>{
    e.preventDefault();if(busy)return;busy=true;$('query-submit').disabled=true;$('query-export').disabled=true;$('query-results').hidden=true;result=null;lastQuery=null;show('Consultando Oracle…');
    try{const query=params(),response=await fetch('/Explore/Data?'+query),data=await response.json();if(!response.ok)throw Error(data.error||'No se pudo completar la consulta.');
      result=data;lastQuery=query.toString();
      if(!query.has('start')){start.value=data.window.start.slice(0,16);end.value=data.window.end.slice(0,16);}
      show(data.rows.length+' filas · '+data.window.start.slice(0,19)+' a '+data.window.end.slice(0,19)+' UTC. '+data.note);$('query-results').hidden=false;$('query-export').disabled=data.rows.length===0;renderTable();renderSelectors();draw();
    }catch(error){show(error.message||'Error de conexión.',true);}finally{busy=false;$('query-submit').disabled=false;}
  });
  $('query-export').addEventListener('click',async()=>{
    if(!lastQuery)return;$('query-export').disabled=true;
    try{const response=await fetch('/Explore/Export?'+lastQuery);if(!response.ok){let data=await response.json();throw Error(data.error||'No se pudo exportar.');}
      const url=URL.createObjectURL(await response.blob()),link=document.createElement('a');link.href=url;link.download='hydrocloud-'+result.product+(response.headers.get('X-HydroCloud-Truncated')?'‑PARCIAL‑2000':'')+'.csv';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    }catch(error){show(error.message,true);}finally{$('query-export').disabled=false;}
  });
  function renderTable(){const table=document.createElement('table');table.className='cyber-table';const head=document.createElement('thead'),tr=document.createElement('tr');for(const col of result.columns){const th=document.createElement('th');th.textContent=col;tr.append(th);}head.append(tr);table.append(head);const body=document.createElement('tbody');for(const row of result.rows){const tr=document.createElement('tr');for(const col of result.columns){const td=document.createElement('td');td.textContent=row[col]??'—';tr.append(td);}body.append(tr);}table.append(body);$('result-table').replaceChildren(table);}
  const seriesKey=row=>[row.SENSOR_ID,row.VARIABLE,row.DCP_ID,row.TIPO_PERIODO].filter(x=>x!=null).join(' · ')||'Serie';
  function renderSelectors(){const series=$('chart-series'),metric=$('chart-metric');series.replaceChildren();metric.replaceChildren();for(const key of new Set(result.rows.map(seriesKey))){series.add(new Option(key,key));}for(const col of result.columns.filter(c=>result.rows.some(r=>typeof r[c]==='number'))){metric.add(new Option(col,col));}}
  $('chart-series').addEventListener('change',draw);$('chart-metric').addEventListener('change',draw);
  function draw(){const svg=$('series-chart');svg.replaceChildren();const metric=$('chart-metric').value,rows=result.rows.filter(r=>seriesKey(r)===$('chart-series').value),time=result.columns[0];
    const points=rows.filter(r=>typeof r[metric]==='number'&&Number.isFinite(Date.parse(r[time]))).map(r=>({t:Date.parse(r[time]),v:r[metric]}));
    if(!points.length){
      $('chart-summary').textContent='No hay valores numéricos para graficar. Revisa la tabla; ausencia de datos no significa cero.';
      if($('kpi-total-obs')) $('kpi-total-obs').textContent = '0';
      if($('kpi-min-val')) $('kpi-min-val').textContent = '—';
      if($('kpi-avg-val')) $('kpi-avg-val').textContent = '—';
      if($('kpi-max-val')) $('kpi-max-val').textContent = '—';
      if($('kpi-sum-val')) $('kpi-sum-val').textContent = '—';
      return;
    }
    const vals = points.map(p=>p.v);
    const min=Math.min(...vals),max=Math.max(...vals),sum=vals.reduce((a,b)=>a+b,0),avg=sum/vals.length;
    
    // Actualizar Tarjetas KPI
    if($('kpi-total-obs')) $('kpi-total-obs').textContent = points.length.toLocaleString();
    if($('kpi-min-val')) $('kpi-min-val').textContent = min.toFixed(2);
    if($('kpi-avg-val')) $('kpi-avg-val').textContent = avg.toFixed(2);
    if($('kpi-max-val')) $('kpi-max-val').textContent = max.toFixed(2);
    if($('kpi-sum-val')) $('kpi-sum-val').textContent = sum.toFixed(2);

    const t0=Date.parse(result.window.start),t1=Date.parse(result.window.end),width=t1-t0||1,range=max-min||1;
    const node=(tag,attrs,text)=>{const el=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v]of Object.entries(attrs))el.setAttribute(k,v);if(text)el.textContent=text;svg.append(el);return el;};
    node('line',{x1:85,y1:280,x2:980,y2:280,stroke:'#1e2d44'});node('line',{x1:85,y1:25,x2:85,y2:280,stroke:'#1e2d44'});
    node('text',{x:5,y:35,fill:'#00f2fe','font-size':13,'font-weight':'bold'},max.toFixed(2));
    node('text',{x:5,y:280,fill:'#4facfe','font-size':13,'font-weight':'bold'},min.toFixed(2));
    node('text',{x:85,y:315,fill:'#8b9bb4','font-size':12},result.window.start.slice(0,16)+' UTC');
    node('text',{x:760,y:315,fill:'#8b9bb4','font-size':12},result.window.end.slice(0,16)+' UTC');
    
    // Trazar puntos Neón
    for(const p of points) {
      const cx = 85+(p.t-t0)/width*895;
      const cy = 270-(p.v-min)/range*230;
      node('circle',{cx:cx,cy:cy,r:3.5,fill:'#00f2fe',stroke:'#0072ff','stroke-width':1});
    }
    $('chart-summary').textContent=points.length+' observaciones de '+metric+'. Mínimo: '+min.toFixed(2)+'; Máximo: '+max.toFixed(2)+'; Suma: '+sum.toFixed(2)+'. Puntos de precisión sin interpolación. Estadísticas de las filas en pantalla.';
  }
})();
