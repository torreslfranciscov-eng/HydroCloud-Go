(() => {
  'use strict';
  const $=id=>document.getElementById(id), auth=$('explorer').dataset.authenticated==='true';
  const start=$('query-start'),end=$('query-end'),station=$('query-station'),status=$('query-status');
  const queryDialog=$('query-dialog');
  function openQueryDialog(){
    if(typeof setGoesView==='function')setGoesView(false);
    if($('query-product')&&!$('query-product').value)$('query-product').value='variables';
    if(typeof queryDialog.showModal==='function'){if(!queryDialog.open)queryDialog.showModal();}
    else queryDialog.setAttribute('open','');
    if(typeof station.focus==='function')setTimeout(()=>station.focus(),0);
    setTimeout(()=>{if(station.value)runQuery(null,false);},0);
  }
  function closeQueryDialog(){if(typeof queryDialog.close==='function')queryDialog.close();else queryDialog.removeAttribute('open');}
  $('open-query-dialog').addEventListener('click',openQueryDialog);
  $('close-query-dialog').addEventListener('click',closeQueryDialog);
  queryDialog.addEventListener('click',event=>{if(event.target===queryDialog)closeQueryDialog();});
  const now=new Date();end.value=now.toISOString().slice(0,16);start.value=new Date(now.getTime()-7*86400000+60000).toISOString().slice(0,16);
  end.max=now.toISOString().slice(0,16);if(!auth) start.min=start.value;
  const period=$('query-period');
  function updatePeriod(){
    const automatic=period.value==='last7';start.disabled=automatic;end.disabled=automatic;
    if($('query-form').classList)$('query-form').classList.toggle('is-automatic',automatic);
    const current=new Date();end.max=current.toISOString().slice(0,16);
    if(!auth)start.min=new Date(current.getTime()-7*86400000+60000).toISOString().slice(0,16);
    if(automatic){start.value=new Date(current.getTime()-7*86400000+60000).toISOString().slice(0,16);end.value=current.toISOString().slice(0,16);}
  }
  period.addEventListener('change',updatePeriod);updatePeriod();
  let stations=[],upstreamStations=[],map=null,markers=null,cycloneLayer=null,earthquakeLayer=null,mapFitted=false,result=null,lastQuery=null,busy=false;
  let baseLayers={},activeBaseLayer=null,lastMapReveal=0;
  let weatherLayers={clouds:null,radar:null},radarRefreshTimer=null,radarRequest=0;
  const weatherState={clouds:'',radar:''};
  let chartMode='single',availableSeries=[],selectedSeries=[],stockChart=null;
  let cyclones=[],earthquakes=[];
  const signals=new Map();
  const signalDetails=new Map();
  const upstreamConditions=new Map();
  const latestLevels=new Map();let levelsLoaded=false,levelsFailed=false;
  const signalColors={recent:'#15803d',week:'#d39100',historical:'#dc2626',empty:'#7f1d1d',unknown:'#64748b'};
  const signalLabels={recent:'TX a tiempo según el intervalo configurado',week:'TX retrasada respecto al intervalo configurado',historical:'Fuera de línea: última TX fuera del margen operativo',empty:'DCP configurado sin historial de TX',unknown:'Sin verificar: no hay DCP vinculado o la consulta falló'};
  const signalShort={recent:'TX a tiempo',week:'TX retrasada',historical:'Fuera de línea',empty:'Sin historial de TX',unknown:'Sin verificar'};
  const cycloneLabels={TD:'Depresión tropical',TS:'Tormenta tropical',HU:'Huracán',SD:'Depresión subtropical',SS:'Tormenta subtropical',PT:'Ciclón postropical'};
  const show=(message,error=false)=>{status.textContent=message;status.className=error?'error':'';};
  const stationIsDam=s=>s.isDam===true||s.IsDam===true||s.ESPRESA===1||s.espresa===1;
  const stationMarkerIcon=(state,isDam)=>L.divIcon({
    className:'station-map-marker station-map-marker-'+state+(isDam?' station-map-marker-dam':' station-map-marker-site'),
    html:'<svg class="station-pin-svg" viewBox="0 0 48 58" aria-hidden="true"><path class="station-pin-body" d="M24 1C11.3 1 3 10.1 3 22.5 3 38.1 24 57 24 57s21-18.9 21-34.5C45 10.1 36.7 1 24 1Z"/>'+(isDam?'<path class="dam-wall" d="M14 18h20l4 16H10l4-16Z"/><path class="dam-gate" d="M20 21h3v10h-3zm6 0h3v10h-3z"/><path class="dam-water" d="M9 37c3-2.3 5.5-2.3 8.5 0s5.5 2.3 8.5 0 5.5-2.3 8.5 0 5.5 2.3 8.5 0"/>':'<circle class="station-node" cx="24" cy="23" r="4"/><path class="station-signal" d="M17 20a8 8 0 0 0 0 6m14-6a8 8 0 0 1 0 6M13 16a13 13 0 0 0 0 14m22-14a13 13 0 0 1 0 14"/><path class="station-mast" d="M24 27v8m-5 0h10"/>')+'</svg>',
    iconSize:[22,28],iconAnchor:[11,27],popupAnchor:[0,-25]
  });
  const stationKey=id=>String(id||'').toLowerCase();
  const compactLocalTime=value=>new Intl.DateTimeFormat('es-MX',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}).format(new Date(value))+' local';
  const compactUtcTime=value=>new Intl.DateTimeFormat('es-MX',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit',hour12:false,timeZone:'UTC'}).format(new Date(value))+' UTC';
  function elapsedLabel(milliseconds){
    const minutes=Math.max(1,Math.round(milliseconds/60000));
    if(minutes<60)return minutes+' min';
    const hours=Math.floor(minutes/60),rest=minutes%60;
    return hours+' h'+(rest?' '+rest+' min':'');
  }
  function formatSigned(value,digits=3){
    const sign=value>0?'+':value<0?'−':'';
    return sign+Math.abs(value).toLocaleString('es-MX',{maximumFractionDigits:digits});
  }
  const metricIsFresh=(metric,hours=6)=>metric&&metric.timestamp&&Date.now()-new Date(metric.timestamp).getTime()<=hours*3600000;
  function upstreamAssessment(condition){
    const flowFresh=metricIsFresh(condition?.flow)&&condition.flow.valid!==false&&condition.flow.value!==null;
    const levelFresh=metricIsFresh(condition?.level)&&condition.level.valid!==false&&condition.level.value!==null;
    const rising=levelFresh&&condition.level.previousValue!==null&&condition.level.previousValue!==undefined&&Number(condition.level.value)-Number(condition.level.previousValue)>.01;
    const rainy=condition?.rain6Hours!==null&&condition?.rain6Hours!==undefined&&Number(condition.rain6Hours)>0;
    if(flowFresh)return {state:'measured',text:'Aporte medido por caudal'};
    if(rainy&&rising)return {state:'likely',text:'Señal compatible con aportación'};
    if(rainy)return {state:'watch',text:'Lluvia reciente · respuesta pendiente'};
    if(rising)return {state:'watch',text:'Nivel subiendo · origen no determinado'};
    if(!levelFresh&&condition?.rain6Hours===null)return {state:'unknown',text:'Sin datos hidrológicos recientes'};
    return {state:'quiet',text:'Sin señal de aumento · no implica aporte cero'};
  }
  function appendUpstreamCondition(container,condition){
    const panel=document.createElement('div');panel.className='upstream-condition';
    if(!condition){const empty=document.createElement('span');empty.className='upstream-condition-empty';empty.textContent='Cargando condiciones…';panel.append(empty);container.append(panel);return;}
    const levelRow=document.createElement('div'),levelLabel=document.createElement('span'),levelValue=document.createElement('strong');levelRow.className='upstream-condition-row';levelLabel.textContent='Nivel';
    if(metricIsFresh(condition.level)&&condition.level.valid!==false&&condition.level.value!==null){
      const delta=condition.level.previousValue===null||condition.level.previousValue===undefined?null:Number(condition.level.value)-Number(condition.level.previousValue);
      levelValue.textContent=Number(condition.level.value).toLocaleString('es-MX',{maximumFractionDigits:2})+' '+condition.level.unit+(delta===null?'':delta>.01?' ↑':delta<-.01?' ↓':' →');
    }else levelValue.textContent=condition.level?.valid===false?'Dato no válido':'Sin dato reciente';
    levelRow.append(levelLabel,levelValue);
    const rainRow=document.createElement('div'),rainLabel=document.createElement('span'),rainValue=document.createElement('strong');rainRow.className='upstream-condition-row';rainLabel.textContent='Lluvia 6 h';rainValue.textContent=condition.rain6Hours===null||condition.rain6Hours===undefined?'Sin dato':Number(condition.rain6Hours).toLocaleString('es-MX',{maximumFractionDigits:1})+' '+condition.rainUnit;rainRow.append(rainLabel,rainValue);
    panel.append(levelRow,rainRow);
    if(condition.flow?.value!==null&&condition.flow?.value!==undefined){const flowRow=document.createElement('div'),flowLabel=document.createElement('span'),flowValue=document.createElement('strong');flowRow.className='upstream-condition-row';flowLabel.textContent='Caudal';flowValue.textContent=Number(condition.flow.value).toLocaleString('es-MX',{maximumFractionDigits:2})+' '+condition.flow.unit;flowRow.append(flowLabel,flowValue);panel.append(flowRow);}
    else if(condition.waterVelocity?.value!==null&&condition.waterVelocity?.value!==undefined){const velocityRow=document.createElement('div'),velocityLabel=document.createElement('span'),velocityValue=document.createElement('strong');velocityRow.className='upstream-condition-row';velocityLabel.textContent='Velocidad';velocityValue.textContent=Number(condition.waterVelocity.value).toLocaleString('es-MX',{maximumFractionDigits:2})+' '+condition.waterVelocity.unit;velocityRow.append(velocityLabel,velocityValue);panel.append(velocityRow);}
    const assessment=upstreamAssessment(condition),badge=document.createElement('span');badge.className='upstream-assessment '+assessment.state;badge.textContent=assessment.text;panel.append(badge);container.append(panel);
  }
  function appendLevelSparkline(container,level){
    const history=(level.history||[]).map(point=>({time:new Date(point.timestamp).getTime(),value:Number(point.value)})).filter(point=>Number.isFinite(point.time)&&Number.isFinite(point.value));
    if(history.length<2)return;
    const values=history.map(point=>point.value),min=Math.min(...values),max=Math.max(...values),start=history[0].time,end=history[history.length-1].time,duration=Math.max(end-start,1);
    const visibleSpan=Math.max(max-min,.25),middle=(min+max)/2,scaleMin=middle-visibleSpan/2,scaleMax=middle+visibleSpan/2;
    const smoothed=values.map((_,index)=>{
      const from=Math.max(0,index-1),to=Math.min(values.length-1,index+1),window=values.slice(from,to+1);
      return window.reduce((sum,item)=>sum+item,0)/window.length;
    });
    const width=208,height=46,padding=3;
    const coordinates=history.map(point=>{
      const x=padding+(point.time-start)/duration*(width-padding*2),y=padding+(scaleMax-point.value)/visibleSpan*(height-padding*2);
      return [x,y];
    });
    const smoothCoordinates=history.map((point,index)=>{
      const x=padding+(point.time-start)/duration*(width-padding*2),y=padding+(scaleMax-smoothed[index])/visibleSpan*(height-padding*2);
      return [x,y];
    });
    const chart=document.createElement('div'),header=document.createElement('div'),title=document.createElement('span'),range=document.createElement('span'),svg=document.createElementNS('http://www.w3.org/2000/svg','svg'),area=document.createElementNS('http://www.w3.org/2000/svg','polygon'),rawLine=document.createElementNS('http://www.w3.org/2000/svg','polyline'),line=document.createElementNS('http://www.w3.org/2000/svg','polyline'),dot=document.createElementNS('http://www.w3.org/2000/svg','circle');
    chart.className='station-tooltip-sparkline';header.className='station-tooltip-sparkline-header';title.textContent='Tendencia · '+elapsedLabel(end-start);range.textContent='Δ '+(max-min).toLocaleString('es-MX',{minimumFractionDigits:2,maximumFractionDigits:2})+' '+(level.unit&&level.unit!=='--'?level.unit:'');header.append(title,range);
    svg.setAttribute('viewBox','0 0 '+width+' '+height);svg.setAttribute('role','img');svg.setAttribute('aria-label','Tendencia suavizada del nivel durante las últimas seis horas; la línea tenue representa las lecturas observadas');
    const rawPoints=coordinates.map(point=>point.join(',')).join(' '),linePoints=smoothCoordinates.map(point=>point.join(',')).join(' '),last=coordinates[coordinates.length-1];
    area.setAttribute('points',padding+','+height+' '+linePoints+' '+(width-padding)+','+height);area.setAttribute('class','station-tooltip-sparkline-area');
    rawLine.setAttribute('points',rawPoints);rawLine.setAttribute('class','station-tooltip-sparkline-raw');rawLine.setAttribute('fill','none');
    line.setAttribute('points',linePoints);line.setAttribute('class','station-tooltip-sparkline-line');line.setAttribute('fill','none');
    dot.setAttribute('cx',String(last[0]));dot.setAttribute('cy',String(last[1]));dot.setAttribute('r','2.7');dot.setAttribute('class','station-tooltip-sparkline-dot');
    svg.append(area,rawLine,line,dot);
    chart.append(header,svg);container.append(chart);
  }
  function appendUpstreamSummary(container,stationRow){
    const relations=upstreamStations.filter(item=>stationKey(item.damStationId)===stationKey(stationRow.id));
    if(!relations.length)return;
    const section=document.createElement('div'),header=document.createElement('div'),label=document.createElement('span'),count=document.createElement('strong');
    section.className='station-tooltip-upstream';header.className='station-tooltip-upstream-header';label.textContent='Estaciones aguas arriba';count.textContent=String(relations.length);header.append(label,count);
    const conditions=relations.map(item=>upstreamConditions.get(stationKey(item.stationId))).filter(Boolean),rainy=conditions.filter(item=>Number(item.rain6Hours)>0).length,rising=conditions.filter(item=>metricIsFresh(item.level)&&item.level.valid!==false&&item.level.previousValue!==null&&Number(item.level.value)-Number(item.level.previousValue)>.01).length,flows=conditions.filter(item=>metricIsFresh(item.flow)&&item.flow.valid!==false).length;
    const hydro=document.createElement('span');hydro.className='station-tooltip-upstream-hydro';hydro.textContent=conditions.length?rainy+' lluvia · '+rising+' ↑ · '+(flows?flows+' caudal':'sin Q'):'Consultando…';
    section.append(header,hydro);container.append(section);
  }
  function appendLevelTooltip(container,s){
    if(!stationIsDam(s))return;
    const reading=document.createElement('div');reading.className='station-tooltip-reading';
    if(!levelsLoaded||levelsFailed){
      const empty=document.createElement('span');empty.className='station-tooltip-empty';
      empty.textContent=levelsLoaded?'Nivel no disponible por error de conexión.':'Cargando última lectura…';
      reading.append(empty);container.append(reading);return;
    }
    const level=latestLevels.get(stationKey(s.id));
    if(!level||level.value===null||level.value===undefined||!level.timestamp){
      const empty=document.createElement('span');empty.className='station-tooltip-empty';
      empty.textContent=!level?'Sin sensor de nivel configurado.':'Sensor configurado, aún sin lecturas.';
      reading.append(empty);container.append(reading);return;
    }
    const valueRow=document.createElement('div'),value=document.createElement('span'),unit=document.createElement('span'),meta=document.createElement('span');
    valueRow.className='station-tooltip-value-row';
    value.className='station-tooltip-value';value.textContent=Number(level.value).toLocaleString('es-MX',{maximumFractionDigits:3});
    unit.className='station-tooltip-unit';unit.textContent=level.unit&&level.unit!=='--'?level.unit:'';
    meta.className='station-tooltip-meta';meta.textContent=compactLocalTime(level.timestamp);
    valueRow.append(value,unit);reading.append(valueRow,meta);appendLevelSparkline(reading,level);
    if(level.previousValue!==null&&level.previousValue!==undefined&&level.previousTimestamp){
      const delta=Number(level.value)-Number(level.previousValue),elapsed=new Date(level.timestamp)-new Date(level.previousTimestamp),hours=elapsed/3600000;
      const trendHistory=(level.history||[]).map(point=>({time:new Date(point.timestamp).getTime(),value:Number(point.value)})).filter(point=>Number.isFinite(point.time)&&Number.isFinite(point.value));
      const trendEnd=trendHistory.length?trendHistory[trendHistory.length-1].time:0,recent=trendHistory.filter(point=>point.time>=trendEnd-3600000);
      let trendRate=hours>0?delta/hours:0;
      if(recent.length>=2){
        const origin=recent[0].time,x=recent.map(point=>(point.time-origin)/3600000),meanX=x.reduce((sum,item)=>sum+item,0)/x.length,meanY=recent.reduce((sum,item)=>sum+item.value,0)/recent.length;
        const denominator=x.reduce((sum,item)=>sum+(item-meanX)**2,0);
        if(denominator>0)trendRate=x.reduce((sum,item,index)=>sum+(item-meanX)*(recent[index].value-meanY),0)/denominator;
      }
      const direction=Math.abs(trendRate)<.01?'stable':trendRate>0?'up':'down',trendText=direction==='up'?'Subiendo · 1 h':direction==='down'?'Bajando · 1 h':'Estable · 1 h';
      const comparison=document.createElement('div'),trendRow=document.createElement('div'),arrow=document.createElement('span'),change=document.createElement('strong'),trend=document.createElement('span');
      comparison.className='station-tooltip-comparison trend-'+direction;
      trendRow.className='station-tooltip-trend-row';arrow.className='station-tooltip-arrow';arrow.textContent=direction==='up'?'↑':direction==='down'?'↓':'→';
      change.className='station-tooltip-change';change.textContent='Δ '+formatSigned(delta)+' '+(level.unit&&level.unit!=='--'?level.unit:'')+' · '+elapsedLabel(elapsed);
      trend.className='station-tooltip-trend';trend.textContent=trendText.replace(' · 1 h','')+' · '+formatSigned(trendRate)+' '+(level.unit&&level.unit!=='--'?level.unit:'u')+'/h';
      trendRow.append(arrow,change,trend);comparison.append(trendRow);reading.append(comparison);
    } else {
      const noComparison=document.createElement('span');noComparison.className='station-tooltip-no-comparison';noComparison.textContent='Aún no hay una lectura anterior para comparar.';reading.append(noComparison);
    }
    if(level.valid===false||level.previousValid===false){const warning=document.createElement('span');warning.className='station-tooltip-warning';warning.textContent=level.valid===false?'El último dato está marcado como no válido':'La lectura anterior está marcada como no válida';reading.append(warning);}
    appendUpstreamSummary(reading,s);container.append(reading);
  }

  function getStationCoords(s) {
    let lat = s.latitude ?? s.Latitude ?? s.LATITUD ?? s.lat;
    let lon = s.longitude ?? s.Longitude ?? s.LONGITUD ?? s.lng ?? s.lon;
    if (lat === null || lat === undefined || lon === null || lon === undefined) return null;

    lat = parseFloat(lat);
    lon = parseFloat(lon);

    if (isNaN(lat) || isNaN(lon) || (lat === 0 && lon === 0)) return null;

    // Si la latitud y longitud están invertidas (ej. lat=99.15 y lon=19.43)
    if (Math.abs(lat) > 90 && Math.abs(lon) <= 90) {
      const temp = lat;
      lat = lon;
      lon = temp;
    }

    // Convertir formato Grados-Minutos-Segundos (DMS, ej. 192530 o 991530) si aplica
    if (Math.abs(lat) > 90) {
      const deg = Math.floor(Math.abs(lat) / 10000);
      const min = Math.floor((Math.abs(lat) % 10000) / 100);
      const sec = Math.abs(lat) % 100;
      lat = (deg + min / 60 + sec / 3600) * (lat < 0 ? -1 : 1);
    }
    if (Math.abs(lon) > 180) {
      const deg = Math.floor(Math.abs(lon) / 10000);
      const min = Math.floor((Math.abs(lon) % 10000) / 100);
      const sec = Math.abs(lon) % 100;
      lon = (deg + min / 60 + sec / 3600) * (lon < 0 ? -1 : 1);
    }

    // En México, la longitud oeste siempre es negativa (-86° a -118° W).
    // Si en la BD viene como valor positivo (ej. 99.15), se ajusta a -99.15 para ubicarla en México.
    if (lon > 80 && lon < 130) {
      lon = -lon;
    }

    if (Math.abs(lat) <= 90 && Math.abs(lon) <= 180) {
      return [lat, lon];
    }
    return null;
  }

  function populateMap() {
    if(!map) initializeMap();
    if(!map||!markers)return;
    markers.clearLayers();const points=[];let upstreamDrawn=0;
    const filter=$('map-filter').value,visible=[];
    for(const s of stations){
      const state=signals.get(s.id)||'unknown',isDam=stationIsDam(s);
      if((filter==='dams'&&!isDam)||(filter!=='all'&&filter!=='dams'&&filter!==state))continue;
      const coords=getStationCoords(s);if(coords)visible.push({s,state,isDam,coords});
    }
    let displayGroups=visible.map(item=>[item]);
    if(filter==='all'&&typeof map.getZoom==='function'&&typeof map.project==='function'&&map.getZoom()<9){
      const cells=new Map(),cellSize=map.getZoom()<=5?44:36;
      for(const item of visible){
        const point=map.project(item.coords,map.getZoom()),key=Math.floor(point.x/cellSize)+':'+Math.floor(point.y/cellSize);
        if(!cells.has(key))cells.set(key,[]);cells.get(key).push(item);
      }
      displayGroups=[...cells.values()];
    }
    for(const group of displayGroups){
      if(group.length>1){
        const coords=[group.reduce((sum,item)=>sum+item.coords[0],0)/group.length,group.reduce((sum,item)=>sum+item.coords[1],0)/group.length];
        const order=['recent','week','historical','empty','unknown'],counts=Object.fromEntries(order.map(state=>[state,group.filter(item=>item.state===state).length]));
        let cursor=0;const stops=[];
        for(const state of order){if(!counts[state])continue;const end=cursor+counts[state]/group.length*100;stops.push(signalColors[state]+' '+cursor.toFixed(1)+'% '+end.toFixed(1)+'%');cursor=end;}
        const summary=order.filter(state=>counts[state]).map(state=>counts[state]+' '+signalShort[state].toLowerCase()).join(' · ');
        const clusterIcon=L.divIcon({className:'station-cluster'+(group.some(item=>item.isDam)?' station-cluster-has-dam':''),html:'<span class="station-cluster-ring" style="background:conic-gradient('+stops.join(',')+')"><b>'+group.length+'</b></span>',iconSize:[32,32],iconAnchor:[16,16]});
        const cluster=L.marker(coords,{icon:clusterIcon});
        cluster.bindTooltip(group.length+' estaciones · '+summary+' · acercar para separar',{direction:'top',opacity:.95});
        if(typeof cluster.on==='function')cluster.on('click',()=>map.setView(coords,Math.min(map.getZoom()+2,12)));
        cluster.addTo(markers);for(const item of group)points.push(item.coords);continue;
      }
      const {s,state,isDam,coords}=group[0];
      const box=document.createElement('article'),header=document.createElement('header'),heading=document.createElement('div'),title=document.createElement('strong'),subtitle=document.createElement('span'),statusPill=document.createElement('span');
      box.className='station-popup';header.className='station-popup-heading';heading.className='station-popup-identity';title.textContent=s.name;subtitle.textContent=(isDam?'Presa':'Estación')+' · '+(s.code||'Sin clave');statusPill.className='station-popup-status state-'+state;statusPill.textContent=signalShort[state];heading.append(title,subtitle);header.append(heading,statusPill);box.append(header);
      const tx=signalDetails.get(stationKey(s.id)),metrics=document.createElement('div');metrics.className='station-popup-metrics';
      const addMetric=(label,value)=>{const item=document.createElement('div'),key=document.createElement('span'),data=document.createElement('strong');key.textContent=label;data.textContent=value;item.append(key,data);metrics.append(item);};
      const txDate=tx?.lastTransmission?new Date(tx.lastTransmission):null,txAge=txDate&&Number.isFinite(txDate.getTime())?elapsedLabel(Math.max(0,Date.now()-txDate.getTime()))+' atrás':'Sin registro';
      addMetric('Última TX',txAge);addMetric('Intervalo',tx?.expectedIntervalMinutes?tx.expectedIntervalMinutes+' min':'—');addMetric('DCP',String(tx?.dcpCount??s.dcpCount??0));addMetric('Instrumentos',String(s.sensorCount??'—'));box.append(metrics);
      const channels=document.createElement('div');channels.className='station-popup-channels';for(const [label,active] of [['GOES',s.goes],['GPRS',s.gprs],['Radio',s.radio]]){const chip=document.createElement('span');chip.className=active?'available':'unavailable';chip.textContent=label;channels.append(chip);}box.append(channels);
      const level=latestLevels.get(stationKey(s.id));if(level?.value!==null&&level?.value!==undefined){const reading=document.createElement('div'),readingLabel=document.createElement('span'),readingValue=document.createElement('strong');reading.className='station-popup-reading';readingLabel.textContent=level.sensorType||'Última lectura';readingValue.textContent=Number(level.value).toLocaleString('es-MX',{maximumFractionDigits:3})+' '+(level.unit||'');reading.append(readingLabel,readingValue);box.append(reading);}
      const note=document.createElement('p');note.className='station-popup-note';note.textContent=signalLabels[state];box.append(note);
      const button=document.createElement('button');button.className='station-popup-action';button.textContent='Consultar esta estación';button.type='button';button.addEventListener('click',()=>{station.value=s.id;setGoesView(false);map.closePopup();openQueryDialog();});
      box.append(button);
      const tooltip=document.createElement('div'),tooltipHeader=document.createElement('div'),tooltipTitle=document.createElement('strong'),tooltipBadge=document.createElement('span');
      tooltip.className='station-tooltip';tooltipHeader.className='station-tooltip-header';tooltipTitle.className='station-tooltip-title';tooltipTitle.textContent=s.name;
      tooltipBadge.className='station-tooltip-badge';tooltipBadge.textContent=isDam?'PRESA':'ESTACIÓN';tooltipHeader.append(tooltipTitle,tooltipBadge);
      tooltip.append(tooltipHeader);appendLevelTooltip(tooltip,s);
      const marker=L.marker(coords,{icon:stationMarkerIcon(state,isDam)});
      const popupWidth=(window.innerWidth||1200)<650?300:520;
      marker.bindPopup(box,{className:'station-detail-popup',minWidth:popupWidth,maxWidth:popupWidth}).bindTooltip(tooltip,{className:'dam-data-tooltip',direction:'auto',offset:[0,-14],opacity:1}).addTo(markers);points.push(coords);
    }
    if($('map-filter').value==='dams'){
      const drawnUpstream=new Set();
      for(const relation of upstreamStations){
        const dam=stations.find(item=>stationKey(item.id)===stationKey(relation.damStationId)),damCoords=dam?getStationCoords(dam):null,coords=getStationCoords(relation);
        if(!damCoords||!coords)continue;
        L.polyline([coords,damCoords],{color:relation.relationStatus==='confirmada'?'#0f7185':'#b7791f',weight:1.25,opacity:.5,dashArray:'4 6',interactive:false}).addTo(markers);
        const key=stationKey(relation.stationId);if(drawnUpstream.has(key))continue;drawnUpstream.add(key);
        const tooltip=document.createElement('div'),title=document.createElement('strong'),river=document.createElement('span'),state=document.createElement('span');
        tooltip.className='upstream-tooltip';title.textContent=relation.name;river.textContent=relation.river;state.textContent=relation.relationStatus==='confirmada'?'Aguas arriba · confirmada':'Aguas arriba · por validar';tooltip.append(title,river,state);appendUpstreamCondition(tooltip,upstreamConditions.get(key));
        L.circleMarker(coords,{radius:5,weight:2,color:'#fff',fillColor:relation.relationStatus==='confirmada'?'#0f7185':'#b7791f',fillOpacity:1}).bindTooltip(tooltip,{className:'upstream-data-tooltip',direction:'top',opacity:1}).addTo(markers);
        points.push(coords);upstreamDrawn++;
      }
    }
    if(points.length&&!mapFitted){mapFitted=true;map.fitBounds(points,{padding:[20,20],maxZoom:10});}
    if($('map-status').dataset.state==='connected')$('map-status').textContent=$('map-filter').value==='dams'?stations.filter(stationIsDam).length+' presas · '+upstreamDrawn+' estaciones aguas arriba relacionadas':points.length+' estaciones con ubicación en el mapa · '+stations.length+' en catálogo';
    animateMapSymbols('#station-map .station-pin-svg, #station-map .station-cluster-ring');
  }
  function refreshSignals(){
    for(const state of Object.keys(signalColors)){const counter=$('count-'+state);if(counter)counter.textContent=stations.filter(s=>(signals.get(s.id)||'unknown')===state).length;}
    $('count-dams').textContent=stations.filter(stationIsDam).length;
    for(const option of station.options){const s=stations.find(s=>s.id===option.value);if(s)option.textContent=(stationIsDam(s)?'Presa · ':'')+s.name+' · '+s.code+' · '+signalShort[signals.get(s.id)||'unknown'];}
    populateMap();
  }
  $('map-filter').addEventListener('change',()=>{mapFitted=false;populateMap();});
  $('reset-map-view').addEventListener('click',()=>{
    if(!map){initializeMap();return;}
    if(typeof map.closePopup==='function')map.closePopup();
    mapFitted=false;populateMap();
  });
  const reducedMotion=()=>typeof window.matchMedia==='function'&&window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  function animateMapSymbols(selector,withScale=true){
    if(reducedMotion()||!window.anime?.animate||typeof document.querySelectorAll!=='function'||Date.now()-lastMapReveal<900)return;
    lastMapReveal=Date.now();const targets=Array.from(document.querySelectorAll(selector)).slice(0,120);if(!targets.length)return;
    const options={opacity:{from:0},duration:520,delay:window.anime.stagger(7),ease:'out(3)'};if(withScale)options.scale={from:.82};window.anime.animate(targets,options);
  }
  function animateLayerChange(){
    const veil=$('map-layer-transition');if(!veil)return;
    if(reducedMotion()||!window.anime?.animate){veil.hidden=true;return;}
    veil.hidden=false;window.anime.animate(veil,{opacity:[0,.32,0],duration:620,ease:'inOut(2)',onComplete:()=>{veil.hidden=true;}});
  }
  function switchBaseLayer(name){
    const next=baseLayers[name];if(!map||!next||next===activeBaseLayer)return;
    if(activeBaseLayer&&typeof map.removeLayer==='function')map.removeLayer(activeBaseLayer);
    next.addTo(map);activeBaseLayer=next;$('base-layer-name').textContent=name==='terrain'?'Relieve':name==='satellite'?'Satélite':'Cartográfico';
    const container=$('station-map');if(container?.classList){container.classList.toggle('basemap-satellite',name==='satellite');container.classList.toggle('basemap-terrain',name==='terrain');}
    animateLayerChange();
  }
  function weatherOpacity(){return Math.max(.2,Math.min(.9,Number($('weather-opacity').value||60)/100));}
  function updateWeatherStatus(){
    const active=[weatherState.clouds,weatherState.radar].filter(Boolean);
    $('weather-layer-status').textContent=active.length?active.join(' · '):'Activa una capa para consultar la imagen reciente.';
  }
  function removeWeatherLayer(name){
    const layer=weatherLayers[name];if(layer&&map&&typeof map.removeLayer==='function')map.removeLayer(layer);weatherLayers[name]=null;weatherState[name]='';updateWeatherStatus();
  }
  function toggleCloudLayer(enabled){
    if(!enabled){removeWeatherLayer('clouds');return;}
    if(!map){initializeMap();}
    if(!weatherLayers.clouds){
      const cacheWindow=Math.floor(Date.now()/600000);
      weatherLayers.clouds=L.tileLayer('https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/GOES-East_ABI_GeoColor/default/GoogleMapsCompatible_Level7/{z}/{y}/{x}.png?v='+cacheWindow,{maxNativeZoom:7,maxZoom:19,opacity:weatherOpacity(),zIndex:320,attribution:'Nubosidad: NASA GIBS · NOAA GOES'});
      weatherLayers.clouds.on('tileerror',()=>{weatherState.clouds='Nubes GOES no disponibles';updateWeatherStatus();});
    }
    weatherLayers.clouds.addTo(map);weatherState.clouds='Nubes GOES · imagen reciente (~40 min)';updateWeatherStatus();animateLayerChange();
  }
  async function loadLatestRadar(){
    if(!$('weather-radar').checked||!map)return;
    const request=++radarRequest;weatherState.radar='Radar: consultando…';updateWeatherStatus();
    try{
      const response=await fetch('https://api.rainviewer.com/public/weather-maps.json',{cache:'no-store'});if(!response.ok)throw new Error('Radar no disponible');
      const data=await response.json(),frames=data?.radar?.past||[],frame=frames[frames.length-1];if(!frame||!data.host)throw new Error('Sin cuadro de radar');
      if(request!==radarRequest||!$('weather-radar').checked)return;
      removeWeatherLayer('radar');
      weatherLayers.radar=L.tileLayer(data.host+frame.path+'/256/{z}/{x}/{y}/2/1_1.png',{maxNativeZoom:7,maxZoom:19,opacity:weatherOpacity(),zIndex:340,attribution:'Radar meteorológico: <a href="https://www.rainviewer.com/" target="_blank" rel="noopener">RainViewer</a>'});
      weatherLayers.radar.on('tileerror',()=>{weatherState.radar='Radar sin cobertura o no disponible';updateWeatherStatus();});weatherLayers.radar.addTo(map);
      weatherState.radar='Lluvia · '+compactUtcTime(Number(frame.time)*1000);updateWeatherStatus();animateLayerChange();
    }catch{
      if(request===radarRequest){removeWeatherLayer('radar');weatherState.radar='Radar temporalmente no disponible';updateWeatherStatus();}
    }finally{
      clearTimeout(radarRefreshTimer);if($('weather-radar').checked)radarRefreshTimer=setTimeout(loadLatestRadar,300000);
    }
  }
  function toggleRadarLayer(enabled){
    clearTimeout(radarRefreshTimer);radarRequest++;
    if(!enabled){removeWeatherLayer('radar');return;}
    loadLatestRadar();
  }
  const layerPanel=$('map-layer-panel'),layerToggle=$('toggle-map-layers');
  layerToggle.addEventListener('click',()=>{
    const opening=layerToggle.getAttribute('aria-expanded')!=='true';layerToggle.setAttribute('aria-expanded',String(opening));
    if(opening){layerPanel.hidden=false;if(!reducedMotion()&&window.anime?.animate)window.anime.animate(layerPanel,{opacity:[0,1],y:[-6,0],scale:[.97,1],duration:260,ease:'out(3)'});}
    else if(!reducedMotion()&&window.anime?.animate)window.anime.animate(layerPanel,{opacity:[1,0],y:[0,-4],duration:180,ease:'in(2)',onComplete:()=>{layerPanel.hidden=true;}});
    else layerPanel.hidden=true;
  });
  for(const name of ['street','terrain','satellite'])$('basemap-'+name).addEventListener('change',event=>{if(event.target.checked)switchBaseLayer(name);});
  $('weather-clouds').addEventListener('change',event=>toggleCloudLayer(event.target.checked));
  $('weather-radar').addEventListener('change',event=>toggleRadarLayer(event.target.checked));
  $('weather-opacity').addEventListener('input',event=>{
    const opacity=weatherOpacity();$('weather-opacity-value').textContent=Math.round(opacity*100)+'%';
    for(const layer of Object.values(weatherLayers))if(layer&&typeof layer.setOpacity==='function')layer.setOpacity(opacity);
  });
  function initializeMap(){
    if(map)return;
    const container = $('station-map');
    if(!container || !window.L){
      setTimeout(initializeMap, 100);
      return;
    }
    map=L.map('station-map').setView([23.5,-102],5);
    markers=L.layerGroup().addTo(map);
    cycloneLayer=L.layerGroup().addTo(map);
    earthquakeLayer=L.layerGroup().addTo(map);
    if(typeof map.on==='function')map.on('zoomend',()=>{if($('map-filter').value==='all')populateMap();});
    const tileError=()=>{if($('map-status').dataset.state!=='error')$('map-status').textContent='El mapa base no está disponible. Las estaciones de DB_ATLAS siguen disponibles en el selector.';};
    baseLayers={
      street:L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'}),
      terrain:L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',{maxZoom:17,attribution:'Mapa: &copy; OpenStreetMap · SRTM | estilo &copy; OpenTopoMap'}),
      satellite:L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',{maxZoom:19,attribution:'Tiles &copy; Esri · fuentes: Esri, Maxar, Earthstar Geographics y colaboradores'})
    };
    activeBaseLayer=baseLayers.street;activeBaseLayer.addTo(map).on('tileerror',tileError);baseLayers.terrain.on('tileerror',tileError);baseLayers.satellite.on('tileerror',tileError);
    populateMap();
  }
  initializeMap();
  function addHazardMetric(container,label,value){
    const metric=document.createElement('div'),key=document.createElement('span'),data=document.createElement('strong');
    key.textContent=label;data.textContent=value;metric.append(key,data);container.append(metric);
  }
  function hazardPopup(kind,title,badge,metrics,note,url,source){
    const card=document.createElement('article'),header=document.createElement('header'),identity=document.createElement('div'),heading=document.createElement('strong'),pill=document.createElement('span'),grid=document.createElement('div'),description=document.createElement('p'),footer=document.createElement('div'),sourceLabel=document.createElement('span');
    card.className='hazard-popup '+kind;header.className='hazard-popup-heading';identity.className='hazard-popup-identity';heading.textContent=title;pill.className='hazard-popup-badge';pill.textContent=badge;identity.append(heading);header.append(identity,pill);grid.className='hazard-popup-metrics';for(const metric of metrics)addHazardMetric(grid,metric[0],metric[1]);description.className='hazard-popup-note';description.textContent=note;footer.className='hazard-popup-footer';sourceLabel.textContent='Fuente: '+source;footer.append(sourceLabel);
    if(url){const link=document.createElement('a');link.textContent='Ver informe oficial ↗';link.href=url;link.target='_blank';link.rel='noopener noreferrer';footer.append(link);}
    card.append(header,grid,description,footer);return card;
  }
  function destinationPoint(latitude,longitude,bearing,distanceNauticalMiles){
    const radius=6371,distance=distanceNauticalMiles*1.852/radius,angle=bearing*Math.PI/180,lat1=latitude*Math.PI/180,lon1=longitude*Math.PI/180;
    const lat2=Math.asin(Math.sin(lat1)*Math.cos(distance)+Math.cos(lat1)*Math.sin(distance)*Math.cos(angle));
    const lon2=lon1+Math.atan2(Math.sin(angle)*Math.sin(distance)*Math.cos(lat1),Math.cos(distance)-Math.sin(lat1)*Math.sin(lat2));
    return [lat2*180/Math.PI,lon2*180/Math.PI];
  }
  function renderCyclones(){
    if(!cycloneLayer)return;cycloneLayer.clearLayers();
    for(const cyclone of cyclones){
      const latitude=Number(cyclone.latitude),longitude=Number(cyclone.longitude);if(!Number.isFinite(latitude)||!Number.isFinite(longitude))continue;
      const classification=cycloneLabels[cyclone.classification]||'Ciclón tropical',wind=Number(cyclone.windKnots),pressure=Number(cyclone.pressureHpa),direction=Number(cyclone.movementDegrees),speed=Number(cyclone.movementKnots);
      const track=Array.isArray(cyclone.track)?cyclone.track.filter(point=>Number.isFinite(Number(point.latitude))&&Number.isFinite(Number(point.longitude))):[];
      if(track.length){
        const observed=track.map(point=>[Number(point.latitude),Number(point.longitude)]);const last=observed[observed.length-1];
        if(Math.abs(last[0]-latitude)>.01||Math.abs(last[1]-longitude)>.01)observed.push([latitude,longitude]);
        if(observed.length>1)L.polyline(observed,{color:'#6d28d9',weight:3,opacity:.88,lineCap:'round',lineJoin:'round',interactive:false,className:'cyclone-observed-track'}).addTo(cycloneLayer);
        for(const point of track){
          const pointClass=point.classification||'CY',pointWind=Number(point.windKnots),pointPressure=Number(point.pressureHpa),tooltip=document.createElement('div'),title=document.createElement('strong'),detail=document.createElement('span');
          tooltip.className='cyclone-track-tooltip';title.textContent=point.timestamp?compactUtcTime(point.timestamp):'Posición histórica';detail.textContent=(cycloneLabels[pointClass]||pointClass)+(Number.isFinite(pointWind)?' · '+pointWind+' kt':'')+(Number.isFinite(pointPressure)?' · '+pointPressure+' hPa':'');tooltip.append(title,detail);
          L.circleMarker([Number(point.latitude),Number(point.longitude)],{radius:3.5,weight:1.5,color:'#fff',fillColor:pointWind>=64?'#c026d3':pointWind>=34?'#7c3aed':'#8b5cf6',fillOpacity:1,className:'cyclone-track-point'}).bindTooltip(tooltip,{direction:'top',opacity:.97}).addTo(cycloneLayer);
        }
      }
      if(Number.isFinite(direction)&&Number.isFinite(speed)&&speed>0){
        const motionEnd=destinationPoint(latitude,longitude,direction,speed*6);
        L.polyline([[latitude,longitude],motionEnd],{color:'#7c3aed',weight:2.5,opacity:.85,dashArray:'7 6',interactive:false,className:'cyclone-motion-vector'}).addTo(cycloneLayer);
        const arrow=L.divIcon({className:'cyclone-motion-arrow',html:'<svg viewBox="0 0 20 20" aria-hidden="true"><path transform="rotate('+direction+' 10 10)" d="M10 1 16 14l-6-3-6 3Z"/></svg>',iconSize:[18,18],iconAnchor:[9,9]});
        L.marker(motionEnd,{icon:arrow,interactive:false,keyboard:false}).addTo(cycloneLayer);
      }
      const icon=L.divIcon({className:'cyclone-map-marker',html:'<span class="cyclone-core" aria-hidden="true"><svg viewBox="0 0 32 32"><path d="M27 13C24 4 11 2 6 10c-4 7 2 16 10 15 6-.7 9-7 6-12-2-4-8-5-11-1-2.5 3 0 7 3 7 2 0 3-2 2-4"/><circle cx="16" cy="16" r="2.4"/></svg></span>',iconSize:[32,32],iconAnchor:[16,16],popupAnchor:[0,-13]});
      const metrics=[['Viento',Number.isFinite(wind)?wind+' kt':'—'],['Presión',Number.isFinite(pressure)?pressure+' hPa':'—'],['Movimiento',Number.isFinite(direction)&&Number.isFinite(speed)?direction+'° · '+speed+' kt':'—'],['Actualizado',cyclone.updated?compactLocalTime(cyclone.updated):'—']];
      const historyNote=track.length?'La línea sólida muestra '+track.length+' posiciones históricas del NHC. ':'Trayectoria histórica no disponible. ';
      const card=hazardPopup('cyclone',cyclone.name,classification,metrics,historyNote+'La línea punteada proyecta seis horas con el movimiento actual; no sustituye el cono de pronóstico.',cyclone.graphicsUrl||cyclone.advisoryUrl,'NHC / NOAA');
      L.marker([latitude,longitude],{icon}).bindPopup(card,{className:'hazard-detail-popup',minWidth:390,maxWidth:390}).bindTooltip(classification+' '+cyclone.name,{direction:'top',offset:[0,-12]}).addTo(cycloneLayer);
    }
    animateMapSymbols('#station-map .cyclone-core');animateMapSymbols('#station-map .cyclone-track-point',false);
  }
  function earthquakeSeverity(magnitude){return magnitude>=6?'Fuerte':magnitude>=5?'Moderado':'Ligero';}
  function renderEarthquakes(){
    if(!earthquakeLayer)return;earthquakeLayer.clearLayers();
    for(const earthquake of earthquakes){
      const latitude=Number(earthquake.latitude),longitude=Number(earthquake.longitude),magnitude=Number(earthquake.magnitude),depth=Number(earthquake.depthKm);if(!Number.isFinite(latitude)||!Number.isFinite(longitude)||!Number.isFinite(magnitude))continue;
      const color=magnitude>=6?'#991b1b':magnitude>=5?'#dc2626':magnitude>=4?'#ea580c':'#d97706',radius=Math.min(13,5+Math.max(0,magnitude-3.5)*2.5);
      const metrics=[['Magnitud','M '+magnitude.toFixed(1)],['Profundidad',Number.isFinite(depth)?depth.toFixed(1)+' km':'—'],['Hora',earthquake.occurred?compactLocalTime(earthquake.occurred):'—'],['Revisión',earthquake.reviewStatus==='reviewed'?'Revisado':'Automático']];
      const note=(earthquake.tsunami?'Indicador de tsunami emitido. ':'')+(earthquake.place||'Ubicación no determinada');
      const card=hazardPopup('earthquake','Sismo M '+magnitude.toFixed(1),earthquakeSeverity(magnitude),metrics,note,earthquake.detailUrl,'USGS');
      L.circleMarker([latitude,longitude],{radius,weight:2,color:'#fff',fillColor:color,fillOpacity:.88,className:'earthquake-map-marker'}).bindPopup(card,{className:'hazard-detail-popup',minWidth:390,maxWidth:390}).bindTooltip('M '+magnitude.toFixed(1)+' · '+earthquake.place,{direction:'top'}).addTo(earthquakeLayer);
    }
    animateMapSymbols('#station-map .earthquake-map-marker',false);
  }
  function toggleHazardLayer(layer,checkbox){
    if(!map||!layer)return;
    if(checkbox.checked){if(typeof map.hasLayer!=='function'||!map.hasLayer(layer))layer.addTo(map);}
    else if(typeof map.removeLayer==='function')map.removeLayer(layer);
  }
  $('layer-cyclones').addEventListener('change',()=>toggleHazardLayer(cycloneLayer,$('layer-cyclones')));
  $('layer-earthquakes').addEventListener('change',()=>toggleHazardLayer(earthquakeLayer,$('layer-earthquakes')));
  const hazardState={cyclones:'loading',earthquakes:'loading'};
  function refreshHazardStatus(){
    const failed=Object.values(hazardState).filter(state=>state==='error').length,loading=Object.values(hazardState).includes('loading');
    $('hazard-status').textContent=loading?'Actualizando fuentes oficiales…':failed===2?'Fuentes no disponibles':failed===1?'Una fuente no disponible':'NHC/NOAA · USGS';
    $('hazard-status').className=failed?'warning':'';
  }
  fetch('/Hazards/Cyclones').then(async response=>{const data=await response.json();if(!response.ok||!Array.isArray(data.items))throw Error(data.error||'Fuente no disponible');return data;}).then(data=>{
    cyclones=data.items;hazardState.cyclones='ready';$('count-cyclones').textContent=cyclones.length;renderCyclones();refreshHazardStatus();
  }).catch(()=>{hazardState.cyclones='error';$('count-cyclones').textContent='—';refreshHazardStatus();});
  fetch('/Hazards/Earthquakes').then(async response=>{const data=await response.json();if(!response.ok||!Array.isArray(data.items))throw Error(data.error||'Fuente no disponible');return data;}).then(data=>{
    earthquakes=data.items;hazardState.earthquakes='ready';$('count-earthquakes').textContent=earthquakes.length;renderEarthquakes();refreshHazardStatus();
  }).catch(()=>{hazardState.earthquakes='error';$('count-earthquakes').textContent='—';refreshHazardStatus();});
  function setStations(rows,message,state='connected'){
    stations=rows;station.replaceChildren();
    for(const s of rows){const option=document.createElement('option');option.value=s.id;option.textContent=s.name+' · '+s.code;station.append(option);}
    station.disabled=rows.length===0;$('map-filter').disabled=rows.length===0;$('query-submit').disabled=rows.length===0;
    mapFitted=false;$('map-status').dataset.state=state;$('map-status').textContent=message;refreshSignals();
    if(queryDialog.open&&!result&&station.value)setTimeout(()=>runQuery(null,false),0);
  }
  function setCatalogUnavailable(message){
    stations=[];signals.clear();mapFitted=false;if(markers)markers.clearLayers();station.replaceChildren();
    const option=document.createElement('option');option.value='';option.textContent='Sin conexión a DB_ATLAS';option.disabled=true;station.append(option);
    station.disabled=true;$('map-filter').disabled=true;$('query-submit').disabled=true;
    for(const state of Object.keys(signalColors)){const counter=$('count-'+state);if(counter)counter.textContent='—';}$('count-dams').textContent='—';
    $('map-status').dataset.state='error';$('map-status').textContent=message;
  }
  const readJson=async(url,errorMessage)=>{const response=await fetch(url),data=await response.json();if(!response.ok)throw Error(data.error||errorMessage);return data;};
  let catalogAttempt=0,enrichmentStarted=false;
  async function loadStationEnrichment(){
    if(enrichmentStarted)return;enrichmentStarted=true;
    try{const data=await readJson('/Explore/Availability','No se pudo verificar el semáforo.');for(const item of data.stations){signals.set(item.stationId,item.state in signalColors?item.state:'unknown');signalDetails.set(stationKey(item.stationId),item);}$('signal-status').textContent='Semáforo TX actualizado: '+new Date(data.checkedAt).toLocaleTimeString()+' · intervalo esperado por DCP';refreshSignals();}
    catch{$('signal-status').textContent='No se pudo verificar el semáforo. Gris no significa sin datos.';}
    try{const rows=await readJson('/Explore/LatestLevels','Lecturas no disponibles.');latestLevels.clear();for(const row of rows)latestLevels.set(stationKey(row.stationId),row);levelsLoaded=true;levelsFailed=false;populateMap();}
    catch{levelsLoaded=true;levelsFailed=true;populateMap();}
    try{upstreamStations=await readJson('/Explore/UpstreamStations','Relaciones no disponibles.');mapFitted=false;populateMap();}
    catch{upstreamStations=[];populateMap();}
    try{const rows=await readJson('/Explore/UpstreamConditions','Condiciones no disponibles.');upstreamConditions.clear();for(const row of rows)upstreamConditions.set(stationKey(row.stationId),row);populateMap();}
    catch{upstreamConditions.clear();populateMap();}
  }
  async function loadStations(){
    if(!stations.length){$('map-status').dataset.state='loading';$('map-status').textContent=catalogAttempt?'DB_ATLAS tarda en responder · reintento '+(catalogAttempt+1)+'…':'Conectando con DB_ATLAS…';}
    try{
      const response=await fetch('/Explore/Stations'),rows=await response.json();if(!response.ok)throw Error(rows.error||'Sin conexión a DB_ATLAS.');if(!Array.isArray(rows)||!rows.length)throw Error('DB_ATLAS respondió sin estaciones; se reintentará.');
      const source=response.headers?.get?.('X-HydroCloud-Catalog'),checked=response.headers?.get?.('X-HydroCloud-Catalog-Checked-At');catalogAttempt=0;
      if(source==='verified-cache'){
        const checkedLabel=checked?new Date(checked).toLocaleString('es-MX'):'fecha anterior';
        setStations(rows,rows.length+' estaciones · última copia verificada de DB_ATLAS ('+checkedLabel+') · reconectando…','stale');
        $('signal-status').textContent='Semáforo pendiente de conexión con DB_ATLAS. Los marcadores permanecen sin verificar.';
        if(typeof window.setTimeout==='function')window.setTimeout(loadStations,30000);
      }else{setStations(rows,rows.length+' estaciones activas y visibles cargadas desde DB_ATLAS.');loadStationEnrichment();}
    }catch(error){
      catalogAttempt++;setCatalogUnavailable((error.message||'Sin conexión a DB_ATLAS.')+' Reintentando automáticamente…');
      if(typeof window.setTimeout==='function')window.setTimeout(loadStations,Math.min(30000,4000*catalogAttempt));
    }
  }
  loadStations();
  let goesViewActive=false,goesSubProduct='transmisiones';
  function setGoesView(active,subProd){
    goesViewActive=Boolean(active);
    if(subProd)goesSubProduct=subProd;
    const btn=$('toggle-goes-view');
    if(btn){
      btn.setAttribute('aria-pressed',String(goesViewActive));
      btn.textContent=goesViewActive?'📈 Ver Variables Hidrológicas':'📡 TX / Telemetría GOES';
    }
    for(const [id,key] of [['goes-tab-transmisiones','transmisiones'],['goes-tab-eficiencia','eficiencia'],['goes-tab-recepcion','recepcion']]){
      const tab=$(id);if(tab)tab.setAttribute('aria-pressed',String(goesSubProduct===key));
    }
  }
  const goesToggleBtn=$('toggle-goes-view');
  if(goesToggleBtn)goesToggleBtn.addEventListener('click',()=>{setGoesView(!goesViewActive);if(station.value&&queryDialog.open)runQuery(null,true);});
  for(const [id,key] of [['goes-tab-transmisiones','transmisiones'],['goes-tab-eficiencia','eficiencia'],['goes-tab-recepcion','recepcion']]){
    const tab=$(id);
    if(tab)tab.addEventListener('click',()=>{setGoesView(true,key);if(station.value&&queryDialog.open)runQuery(null,true);});
  }
  function params(){
    const activeProd=goesViewActive?goesSubProduct:($('query-product').value||'variables');
    const query=new URLSearchParams({stationId:station.value,product:activeProd});
    if(period.value!=='last7'){query.set('start',start.value+':00Z');query.set('end',end.value+':00Z');}
    return query;
  }
  async function runQuery(event,force=true){
    event?.preventDefault();if(busy||!station.value)return;const query=params(),signature=query.toString();if(!force&&result&&lastQuery===signature)return;busy=true;$('query-submit').disabled=true;$('query-export').disabled=true;$('query-results').hidden=true;$('query-note').hidden=true;result=null;lastQuery=null;show('Consultando PostgreSQL…');
    try{const query=params(),response=await fetch('/Explore/Data?'+query),data=await response.json();if(!response.ok)throw Error(data.error||'No se pudo completar la consulta.');
      result=data;lastQuery=query.toString();
      if(!query.has('start')){start.value=data.window.start.slice(0,16);end.value=data.window.end.slice(0,16);}
      show(data.rows.length.toLocaleString()+' filas · '+data.window.start.slice(0,16).replace('T',' ')+' — '+data.window.end.slice(0,16).replace('T',' ')+' UTC'+(data.truncated?' · resultado limitado':''));$('query-note').hidden=false;$('query-note-text').textContent=data.note;$('query-results').hidden=false;$('query-export').disabled=data.rows.length===0;renderGoesMessages();renderTable();renderSelectors();draw();
    }catch(error){show(error.message||'Error de conexión.',true);}finally{busy=false;$('query-submit').disabled=false;}
  }
  $('query-submit').addEventListener('click',()=>setGoesView(false));
  $('query-form').addEventListener('submit',event=>runQuery(event,true));
  $('query-product').addEventListener('change',()=>{setGoesView(false);if(station.value&&queryDialog.open)runQuery(null,true);});
  station.addEventListener('change',()=>{if(station.value&&queryDialog.open)runQuery(null,true);});
  function parseHmsSeconds(hms,fallbackSec){
    const parts=String(hms||'').trim().split(':').map(Number);
    if(parts.length>=2&&parts.every(Number.isFinite))return (parts[0]*3600)+(parts[1]*60)+(parts[2]||0);
    return fallbackSec;
  }
  function formatUtcSlot(ms){
    return new Date(ms).toISOString().replace('T',' ').slice(0,19)+' UTC';
  }
  function parseDomsatHeader37(hdr){
    if(!hdr||hdr.length<37)return null;
    const dcp=hdr.slice(0,8).trim(),tstr=hdr.slice(8,19);
    let tsIso=tstr;
    const yy=Number(tstr.slice(0,2)),ddd=Number(tstr.slice(2,5)),hh=Number(tstr.slice(5,7)),mm=Number(tstr.slice(7,9)),ss=Number(tstr.slice(9,11));
    if([yy,ddd,hh,mm,ss].every(Number.isFinite)&&ddd>=1&&ddd<=366){
      const dt=new Date(Date.UTC(2000+yy,0,1,hh,mm,ss)+(ddd-1)*86400000);
      tsIso=dt.toISOString().replace('T',' ').slice(0,19)+' UTC';
    }
    return {
      dcp,tstr,tsIso,
      failCode:hdr.slice(19,20),
      signalDb:hdr.slice(20,22).trim(),
      freqOffset:hdr.slice(22,24).trim(),
      modIndex:hdr.slice(24,25),
      dataQuality:hdr.slice(25,26),
      channel:hdr.slice(26,29).trim(),
      spacecraft:hdr.slice(29,30),
      uplink:hdr.slice(30,32),
      msgLen:hdr.slice(32,37).trim()
    };
  }
  function decodeGs300Words(payloadStr){
    const clean=String(payloadStr||'').replace(/^[\r\n\s]+|[\r\n\s]+$/g,'');
    if(!clean)return {prefix:'',words:[],note:'Payload vacío'};
    let prefix='',body=clean;
    if(clean.length>=4&&clean.slice(1,3)==='B1'&&[34,96,98].includes(clean.charCodeAt(0))){
      prefix=clean.slice(0,4);body=clean.slice(4);
    }else if(clean.length>1&&[96,98].includes(clean.charCodeAt(0))&&(clean.length-1)%3===0){
      prefix=clean.slice(0,1);body=clean.slice(1);
    }
    const words=[];
    for(let i=0;i+2<body.length;i+=3){
      const trip=body.slice(i,i+3);
      if(trip==='///'){words.push({triplet:trip,raw:null});continue;}
      const c0=trip.charCodeAt(0),c1=trip.charCodeAt(1),c2=trip.charCodeAt(2);
      if([c0,c1,c2].some(c=>c<63||c>126)){words.push({triplet:trip,raw:null,invalid:true});continue;}
      let v=((c0<64?c0:c0-64)<<12)|((c1<64?c1:c1-64)<<6)|(c2<64?c2:c2-64);
      if(v&(1<<17))v-=(1<<18);
      words.push({triplet:trip,raw:v});
    }
    return {prefix,words,remainder:body.slice(words.length*3)};
  }
  function decodeOttBinaryBlocks(payloadStr){
    const clean=String(payloadStr||'').replace(/[\r\n\s]+$/g,'');
    if(clean.length<=5||clean.slice(1,4)!=='OTA'||clean[4]!=='@')return {error:'Prefijo OTT (OTA@) no detectado en el cuerpo',blocks:[]};
    const body=clean.slice(5);
    let bits='';
    for(let i=0;i<body.length;i++){
      const code=body.charCodeAt(i);
      const val=code<64?code:code-64;
      bits=val.toString(2).padStart(6,'0')+bits;
    }
    const bytes=[];
    while(bits.length>0){
      const take=bits.length>=8?8:bits.length;
      bytes.push(parseInt(bits.slice(bits.length-take),2));
      bits=bits.slice(0,bits.length-take);
    }
    if(bytes.length<8)return {error:'Trama OTT incompleta (<8 bytes)',blocks:[]};
    const u8=new Uint8Array(bytes),dv=new DataView(u8.buffer);
    const epoch2000=Date.UTC(2000,0,1,0,0,0);
    const stampMs=epoch2000+(dv.getInt32(0,true)*1000);
    const blocks=[];let pos=4;
    while(pos<bytes.length){
      if(bytes.length-pos<=2)break;
      if(bytes[pos]===0x20&&(bytes[pos+1]||0)===0x00)break;
      if(bytes.length-pos<4)break;
      const interval=dv.getInt16(pos,true),count=dv.getInt16(pos+2,true);pos+=4;
      const width=interval===0?6:2;
      if(interval<0||interval>1000||count<=0||count>1000||pos+width*count>bytes.length)break;
      const values=[];
      for(let i=0;i<count;i++){
        values.push(dv.getInt16(pos,true));
        pos+=width;
      }
      blocks.push({interval,count,values});
    }
    return {stampIso:new Date(stampMs).toISOString().replace('T',' ').slice(0,19)+' UTC',blocks,byteCount:bytes.length};
  }
  function buildDecodedGoesPanel(raw,sched,sensors){
    const wrap=document.createElement('section');wrap.className='goes-decode-panel';
    const decName=String(sched?.decoder||'GS300').trim()||'GS300';
    const rangeMin=Number(sched?.rangeMinutes)||60;
    const domsat=parseDomsatHeader37(raw);
    const payload=raw.length>37?raw.slice(37).replace(/^\r?\n/,''):'';

    // 1. Header summary bar
    if(domsat){
      const hdrBox=document.createElement('div');hdrBox.className='goes-decode-hdr-grid';
      const items=[
        ['Decodificador BD',decName],
        ['DCP (0..8)',domsat.dcp],
        ['Hora Satélite (8..19)',domsat.tstr+' → '+domsat.tsIso],
        ['Falla / Calidad (19,25)',domsat.failCode+' / '+domsat.dataQuality],
        ['Potencia / Frec (20..24)',domsat.signalDb+' dB / '+domsat.freqOffset],
        ['Canal / Sat / Uplink',domsat.channel+' · '+domsat.spacecraft+' · '+domsat.uplink],
        ['Longitud Payload',domsat.msgLen+' B ('+payload.length+' chars)']
      ];
      for(const [k,v] of items){
        const cell=document.createElement('div'),sp=document.createElement('span'),st=document.createElement('strong');
        cell.className='goes-decode-hdr-cell';sp.textContent=k;st.textContent=v;cell.append(sp,st);hdrBox.append(cell);
      }
      wrap.append(hdrBox);
    }

    // Active physical sensors ordered by catalog Order
    const activeSensors=[...(sensors||[])].filter(s=>!s.isCalculated).sort((a,b)=>(Number(a.order??999)-Number(b.order??999))||String(a.sensorId).localeCompare(String(b.sensorId)));

    const tbl=document.createElement('table');tbl.className='goes-decode-table';
    const thead=document.createElement('thead'),htr=document.createElement('tr');
    for(const col of ['Orden · Sensor (Catálogo)','Parámetros','Muestras Crudas en Trama','Valores Decodificados (Ingeniería)','Último Valor']){
      const th=document.createElement('th');th.textContent=col;htr.append(th);
    }
    thead.append(htr);tbl.append(thead);
    const tbody=document.createElement('tbody');

    if(decName==='GS300'){
      const gs=decodeGs300Words(payload);
      let cursor=0;
      for(const s of activeSensors){
        const period=Math.max(1,Number(s.periodMinutes)||10);
        const count=Math.max(1,Math.round(rangeMin/period));
        const dec=Math.max(0,Number(s.decimals)||0);
        const scale=Math.pow(10,dec);
        const slice=gs.words.slice(cursor,cursor+count);
        cursor+=count;
        const tr=document.createElement('tr');
        const td1=document.createElement('td'),td2=document.createElement('td'),td3=document.createElement('td'),td4=document.createElement('td'),td5=document.createElement('td');
        td1.innerHTML='<b>#'+(s.order??'—')+' · '+s.sensorId+'</b> · '+s.name+(s.unit?' ('+s.unit+')':'');
        td2.textContent='c/'+period+'m · '+dec+' dec · '+count+' muestras';
        if(slice.length){
          td3.textContent=slice.map(w=>w.triplet+'='+(w.raw===null?'///':w.raw)).join('  ');
          const scaled=slice.map(w=>w.raw===null?'Faltante':(w.raw/scale).toFixed(dec));
          td4.textContent=scaled.join(' , ')+(s.unit?' '+s.unit:'');
          const lastVal=slice[slice.length-1];
          td5.innerHTML=lastVal&&lastVal.raw!==null?'<strong>'+(lastVal.raw/scale).toFixed(dec)+(s.unit?' '+s.unit:'')+'</strong>':'—';
        }else{
          td3.textContent='(Sin palabras en posición '+cursor+')';td4.textContent='—';td5.textContent='—';
        }
        tr.append(td1,td2,td3,td4,td5);tbody.append(tr);
      }
      if(cursor<gs.words.length){
        const extra=gs.words.slice(cursor);
        const nonZero=extra.filter(w=>w.raw!==0);
        const tr=document.createElement('tr');tr.className='goes-decode-extra-row';
        const td1=document.createElement('td'),td2=document.createElement('td'),td3=document.createElement('td'),td4=document.createElement('td'),td5=document.createElement('td');
        td1.innerHTML='<b>Palabras adicionales / Relleno</b>';
        td2.textContent=extra.length+' palabras tras catálogo (prefijo '+(gs.prefix||'ninguno')+')';
        td3.textContent=extra.slice(0,18).map(w=>w.triplet+'='+(w.raw===null?'///':w.raw)).join('  ')+(extra.length>18?' … (+'+(extra.length-18)+' más)':'');
        td4.textContent=nonZero.length?nonZero.map(w=>w.raw).join(', '):'Relleno @ (todos 0)';
        td5.textContent=extra.length+' words';
        tr.append(td1,td2,td3,td4,td5);tbody.append(tr);
      }
    }else if(decName==='OTTBinario'){
      const ott=decodeOttBinaryBlocks(payload);
      if(ott.error){
        const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=5;td.textContent=ott.error;tr.append(td);tbody.append(tr);
      }else{
        const maxLen=Math.max(ott.blocks.length,activeSensors.length);
        for(let i=0;i<maxLen;i++){
          const blk=ott.blocks[i],s=activeSensors[i];
          const dec=s?Math.max(0,Number(s.decimals)||0):0,scale=Math.pow(10,dec);
          const tr=document.createElement('tr');
          const td1=document.createElement('td'),td2=document.createElement('td'),td3=document.createElement('td'),td4=document.createElement('td'),td5=document.createElement('td');
          td1.innerHTML=s?'<b>#'+(s.order??(i+1))+' · '+s.sensorId+'</b> · '+s.name+(s.unit?' ('+s.unit+')':''):'<b>Bloque OTT #'+(i+1)+' (Sin sensor)</b>';
          td2.textContent=blk?'c/'+blk.interval+'m · '+blk.count+' muestras · '+dec+' dec':'Sin bloque en trama';
          td3.textContent=blk?blk.values.join(', '):'—';
          const scaled=blk?blk.values.map(v=>v<-32700?'FLAG('+v+')':(v/scale).toFixed(dec)):[];
          td4.textContent=scaled.length?scaled.join(' , ')+(s?.unit?' '+s.unit:''):'—';
          td5.innerHTML=scaled.length?'<strong>'+scaled[scaled.length-1]+(s?.unit?' '+s.unit:'')+'</strong>':'—';
          tr.append(td1,td2,td3,td4,td5);tbody.append(tr);
        }
      }
    }else if(decName==='GS'||decName==='CILA_Text'){
      const clean=payload.trim();
      const chunks=decName==='CILA_Text'?clean.split(':'):clean.split(/[\r\n]+/);
      for(const ch of chunks){
        const parts=ch.trim().split(/\s+/).filter(Boolean);
        if(!parts.length||parts[0].toUpperCase()==='NAME')continue;
        const code=parts[0].toUpperCase(),sensorCode=code.padStart(4,'0');
        const s=(sensors||[]).find(x=>x.sensorId===sensorCode||x.sensorId===code);
        const vals=decName==='CILA_Text'&&parts[2]?.startsWith('#')?parts.slice(3):parts.slice(2);
        const intervalTxt=decName==='CILA_Text'&&parts[2]?.startsWith('#')?'offset '+parts[1]+'m · c/'+parts[2].slice(1)+'m':'c/'+(parts[1]||'?')+'m';
        const tr=document.createElement('tr');
        const td1=document.createElement('td'),td2=document.createElement('td'),td3=document.createElement('td'),td4=document.createElement('td'),td5=document.createElement('td');
        td1.innerHTML='<b>Canal '+code+' ('+sensorCode+')</b>'+(s?' · '+s.name+(s.unit?' ('+s.unit+')':''):' · (No mapeado)');
        td2.textContent=intervalTxt+' · '+vals.length+' muestras';
        td3.textContent=ch.trim();
        td4.textContent=vals.join(' , ')+(s?.unit?' '+s.unit:'');
        td5.innerHTML=vals.length?'<strong>'+vals[0]+(s?.unit?' '+s.unit:'')+'</strong>':'—';
        tr.append(td1,td2,td3,td4,td5);tbody.append(tr);
      }
    }else{
      // SMN, SMN_ver2, VAISALA_Protocol_Text, o texto tabular por renglones
      const lines=payload.split(/[\r\n\x00\x04]+/).map(l=>l.trim().replace(/^"+|"+$/g,'')).filter(Boolean);
      lines.forEach((line,idx)=>{
        const tr=document.createElement('tr');
        const td1=document.createElement('td'),td2=document.createElement('td'),td3=document.createElement('td'),td4=document.createElement('td'),td5=document.createElement('td');
        let tableId='default',stampTxt='Línea '+(idx+1),tokens=[];
        const mTab=line.match(/^(02|04|2|4)\s*(\d{8,12}),(.*)$/);
        const mClk=line.match(/^(?:(\d{1,2})\s+)?(\d{4}-\d{2}-\d{2}\s+)?(\d{2}:\d{2}:\d{2})\s+(.+)$/);
        if(mTab){
          tableId=String(Number(mTab[1]));stampTxt='Tabla '+tableId+' · '+mTab[2];tokens=mTab[3].split(',').map(x=>x.trim());
        }else if(mClk){
          tableId=mClk[1]||'default';stampTxt=(mClk[2]||'')+mClk[3];tokens=mClk[4].includes(',')?mClk[4].split(',').map(x=>x.trim()):mClk[4].trim().split(/\s+/);
        }else{
          tokens=line.includes(',')?line.split(',').map(x=>x.trim()):line.split(/\s+/);
        }
        const periodMatch=tableId==='2'?10:tableId==='4'?60:null;
        const tblSensors=periodMatch?activeSensors.filter(s=>Number(s.periodMinutes)===periodMatch):activeSensors;
        td1.innerHTML='<b>Registro #'+(idx+1)+'</b> · '+stampTxt;
        td2.textContent=decName+' · '+tokens.length+' columnas';
        td3.textContent=line;
        td4.textContent=tokens.map((v,colIdx)=>{
          const s=tblSensors[colIdx];
          return (s?s.sensorId+' '+s.name+': ':'C'+(colIdx+1)+': ')+v+(s?.unit?' '+s.unit:'');
        }).join(' | ');
        td5.innerHTML=tokens.length?'<strong>'+tokens[tokens.length-1]+'</strong>':'—';
        tr.append(td1,td2,td3,td4,td5);tbody.append(tr);
      });
    }
    tbl.append(tbody);wrap.append(tbl);
    return wrap;
  }
  function renderGoesMessages(){
    const panel=$('goes-messages-panel'),list=$('goes-messages-list'),summary=$('goes-messages-summary'),dailyStrip=$('goes-daily-strip'),chartCard=$('chart-workspace-card');
    if(!panel||!list||!summary)return;
    const isGoes=Boolean(result&&goesViewActive);
    panel.hidden=!isGoes;
    if(chartCard)chartCard.hidden=Boolean(isGoes&&result.product==='transmisiones');
    if(!isGoes){list.replaceChildren();summary.replaceChildren();if(dailyStrip)dailyStrip.replaceChildren();return;}
    list.replaceChildren();summary.replaceChildren();if(dailyStrip)dailyStrip.replaceChildren();
    if(result.product!=='transmisiones'&&!result.columns.includes('RAW_MESSAGE')){
      const sched=result.goesSchedule||{};
      for(const [k,v] of [['DCP',sched.dcpId||'—'],['1ª TX UTC',sched.firstTransmission||'—'],['Intervalo',sched.interval||'—'],['Esperadas/día',sched.expectedPerDay||24],['Canal / Sat.',(sched.channel??'—')+' · '+(sched.satellite||'GOES-E')],['Registros',result.rows.length.toLocaleString()]]){
        const chip=document.createElement('div'),lbl=document.createElement('span'),val=document.createElement('strong');
        chip.className='goes-summary-chip';lbl.textContent=k;val.textContent=String(v);chip.append(lbl,val);summary.append(chip);
      }
      return;
    }
    const rows=[...result.rows].reverse();
    const sched=result.goesSchedule||{};
    const intervalSec=Math.max(300,parseHmsSeconds(sched.interval||'01:00:00',3600));
    let firstTxSec=parseHmsSeconds(sched.firstTransmission,null);
    if(firstTxSec===null){
      const sampleTs=rows.length?Date.parse(rows[0].TIMESTAMP_MSG||rows[0].TS):NaN;
      if(Number.isFinite(sampleTs)){
        const d=new Date(sampleTs);
        firstTxSec=(d.getUTCHours()*3600+d.getUTCMinutes()*60+d.getUTCSeconds())%intervalSec;
      }else firstTxSec=0;
    }else{
      firstTxSec=firstTxSec%intervalSec;
    }
    const mm=String(Math.floor((firstTxSec%3600)/60)).padStart(2,'0'),ss=String(firstTxSec%60).padStart(2,'0');
    const intervalMin=Math.round(intervalSec/60);
    const expectedPerDay=sched.expectedPerDay||Math.max(1,Math.round(86400/intervalSec));

    // Build expected slots for the last 48 hours up to window.end (or now)
    const endMs=Math.min(Date.now(),Date.parse(result.window?.end)||Date.now());
    const start48Ms=endMs-(48*3600*1000);
    const dayZeroMs=Math.floor(start48Ms/86400000)*86400000;
    const parsedRows=rows.map(r=>({row:r,ms:Date.parse(r.TIMESTAMP_MSG||r.TS)})).filter(x=>Number.isFinite(x.ms));
    const usedRowIdx=new Set();
    const toleranceMs=Math.min(intervalSec*450,900000); // up to 15 min or 45% of interval
    const slots=[];
    for(let t=dayZeroMs+(firstTxSec*1000);t<=endMs+60000;t+=intervalSec*1000){
      if(t<start48Ms)continue;
      if(t>endMs)break;
      let bestIdx=-1,bestDiff=Infinity;
      for(let i=0;i<parsedRows.length;i++){
        if(usedRowIdx.has(i))continue;
        const diff=Math.abs(parsedRows[i].ms-t);
        if(diff<=toleranceMs&&diff<bestDiff){bestDiff=diff;bestIdx=i;}
      }
      if(bestIdx>=0){
        usedRowIdx.add(bestIdx);
        slots.push({expectedMs:t,received:parsedRows[bestIdx].row,receivedMs:parsedRows[bestIdx].ms,deltaSec:Math.round((parsedRows[bestIdx].ms-t)/1000)});
      }else{
        slots.push({expectedMs:t,received:null,receivedMs:null,deltaSec:null});
      }
    }
    slots.reverse(); // newest expected slot first

    const slots24=slots.filter(s=>s.expectedMs>=endMs-(24*3600*1000));
    const exp24=slots24.length||expectedPerDay;
    const rec24=slots24.filter(s=>s.received).length;
    const pct24=exp24?Math.round((rec24*100)/exp24):0;

    const signals=rows.map(r=>Number(r.SIGNAL_STRENGTH)).filter(v=>Number.isFinite(v));
    const avgSig=signals.length?(signals.reduce((a,b)=>a+b,0)/signals.length).toFixed(1)+' dB':'—';
    const goodCount=rows.filter(r=>r.FAILURE_CODE==='G'||r.DATA_QUALITY==='N').length;
    const lastRow=rows[0]||{};
    const dcpCode=sched.dcpId||lastRow.DCP_ID||'—';
    const chanSat=(sched.channel??lastRow.CHANNEL??'—')+' · '+(sched.satellite||lastRow.SPACECRAFT||'GOES-E')+(sched.decoder?' · '+sched.decoder:'');

    const kpis=[
      ['DCP / Horario TX',dcpCode+' · min :'+mm+':'+ss+' (c/'+intervalMin+'m)'],
      ['Últimas 24 h (Rec / Esp)',rec24+' / '+exp24+' ('+pct24+'%)'],
      ['Total periodo (7d)',rows.length+' recibidas'],
      ['Señal prom.',avgSig],
      ['Calidad OK',rows.length?Math.round(goodCount*100/rows.length)+'%':'—'],
      ['Canal / Sat / Decod.',chanSat]
    ];
    for(const [k,v] of kpis){
      const chip=document.createElement('div'),lbl=document.createElement('span'),val=document.createElement('strong');
      chip.className='goes-summary-chip';lbl.textContent=k;val.textContent=String(v);chip.append(lbl,val);summary.append(chip);
    }

    // Daily Expected vs Received strip across the query window
    if(dailyStrip){
      const byDay=new Map();
      for(const item of parsedRows){
        const dayKey=new Date(item.ms).toISOString().slice(0,10);
        byDay.set(dayKey,(byDay.get(dayKey)||0)+1);
      }
      const winStartMs=Date.parse(result.window?.start)||(endMs-7*86400000);
      const dayCards=[];
      for(let dMs=Math.floor(endMs/86400000)*86400000;dMs>=Math.floor(winStartMs/86400000)*86400000;dMs-=86400000){
        const dayKey=new Date(dMs).toISOString().slice(0,10);
        const isToday=dayKey===new Date(endMs).toISOString().slice(0,10);
        let expDay=expectedPerDay;
        if(isToday){
          let countToday=0;
          for(let s=dMs+(firstTxSec*1000);s<=endMs;s+=intervalSec*1000)if(s>=dMs)countToday++;
          expDay=Math.max(1,countToday);
        }
        const recDay=byDay.get(dayKey)||0;
        const pct=Math.min(100,Math.round((recDay*100)/expDay));
        dayCards.push({dayKey,isToday,recDay,expDay,pct});
      }
      const shortMonths=['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic'];
      for(const d of dayCards.slice(0,8)){
        const box=document.createElement('div'),top=document.createElement('div'),dayLbl=document.createElement('span'),pctBadge=document.createElement('strong'),nums=document.createElement('div'),ratioSpan=document.createElement('b'),missSpan=document.createElement('small'),barWrap=document.createElement('div'),barFill=document.createElement('div');
        const stateCls=d.pct>=85?'goes-day-ok':d.pct>=50?'goes-day-warn':'goes-day-miss';
        const [,mStr,dStr]=d.dayKey.split('-');
        const shortDate=Number(dStr)+' '+shortMonths[(Number(mStr)||1)-1];
        const missing=Math.max(0,d.expDay-d.recDay);
        box.className='goes-day-card '+stateCls;
        box.title=d.dayKey+' UTC · Recibidas: '+d.recDay+' de '+d.expDay+' esperadas ('+d.pct+'%) · Faltantes: '+missing;
        top.className='goes-day-top';
        dayLbl.textContent=d.isToday?shortDate+' · Hoy':shortDate;
        pctBadge.textContent=d.pct+'%';
        top.append(dayLbl,pctBadge);
        nums.className='goes-day-nums';
        ratioSpan.textContent=d.recDay+'/'+d.expDay+' TX';
        missSpan.textContent=missing>0?'−'+missing:'OK';
        nums.append(ratioSpan,missSpan);
        barWrap.className='goes-day-bar';barFill.className='goes-day-fill';
        if(barFill.style)barFill.style.width=d.pct+'%';
        barWrap.append(barFill);
        box.append(top,nums,barWrap);
        dailyStrip.append(box);
      }
    }

    if(!slots.length&&!rows.length){
      const empty=document.createElement('p');empty.className='goes-empty-msg';empty.textContent='No se encontraron mensajes GOES en este rango temporal para la estación seleccionada.';list.append(empty);return;
    }

    // Render each Expected vs Received slot (last 48h slots + any extra older received frames)
    for(const slot of slots){
      const row=slot.received;
      const card=document.createElement('article'),head=document.createElement('header'),meta=document.createElement('div'),badges=document.createElement('div');
      card.className='goes-msg-card '+(row?'goes-msg-ok':'goes-msg-missing');
      head.className='goes-msg-head';meta.className='goes-msg-meta';badges.className='goes-msg-badges';

      const statusBadge=document.createElement('strong');
      statusBadge.className='goes-status-badge '+(row?'is-received':'is-missing');
      statusBadge.textContent=row?'✓ RECIBIDA':'✗ NO RECIBIDA';

      const expSpan=document.createElement('span');
      expSpan.className='goes-slot-time';
      expSpan.textContent='Esperada: '+formatUtcSlot(slot.expectedMs);

      const recSpan=document.createElement('span');
      recSpan.className='goes-slot-time '+(row?'goes-slot-rec-ok':'goes-slot-rec-miss');
      if(row){
        const deltaTxt=slot.deltaSec===0?'a tiempo':(slot.deltaSec>0?'+'+slot.deltaSec+'s':slot.deltaSec+'s');
        recSpan.textContent='→ Recibida: '+formatUtcSlot(slot.receivedMs)+' ('+deltaTxt+')';
      }else{
        recSpan.textContent='→ Recibida: Sin recepción en esta ventana horaria';
      }
      meta.append(statusBadge,expSpan,recSpan);

      if(row){
        const sig=Number(row.SIGNAL_STRENGTH);
        const sigPill=document.createElement('span');sigPill.className='goes-pill '+(Number.isFinite(sig)?(sig>=38?'sig-good':sig>=33?'sig-warn':'sig-low'):'');
        sigPill.textContent='Señal: '+(Number.isFinite(sig)?sig+' dB':'—');
        const qualPill=document.createElement('span');qualPill.className='goes-pill '+((row.FAILURE_CODE==='G'&&row.DATA_QUALITY==='N')?'sig-good':'sig-warn');
        qualPill.textContent='Calidad: '+(row.FAILURE_CODE||'?')+'/'+(row.DATA_QUALITY||'?');
        const chanPill=document.createElement('span');chanPill.className='goes-pill';
        chanPill.textContent='DCP '+(row.DCP_ID||dcpCode)+' · CH '+(row.CHANNEL??'—')+' · Sat '+(row.SPACECRAFT??'—')+' · Frec '+(row.FREQUENCY_OFFSET??'—');
        badges.append(sigPill,qualPill,chanPill);
        const raw=row.RAW_MESSAGE?String(row.RAW_MESSAGE):'';
        let decodeContainer=null;
        if(raw){
          const decBtn=document.createElement('button');decBtn.type='button';decBtn.className='goes-decode-btn';
          const decLabel=sched.decoder||'GS300';
          decBtn.textContent='⚙️ Decodificar ('+decLabel+')';
          decBtn.addEventListener('click',()=>{
            if(!decodeContainer){
              decodeContainer=buildDecodedGoesPanel(raw,sched,result.series||[]);
              card.append(decodeContainer);
              decBtn.setAttribute('aria-expanded','true');
              decBtn.textContent='▴ Ocultar decodificación ('+decLabel+')';
            }else{
              const hidden=decodeContainer.hidden;
              decodeContainer.hidden=!hidden;
              decBtn.setAttribute('aria-expanded',String(hidden));
              decBtn.textContent=hidden?'▴ Ocultar decodificación ('+decLabel+')':'⚙️ Decodificar ('+decLabel+')';
            }
          });
          badges.append(decBtn);
        }
        if(raw&&typeof navigator!=='undefined'&&navigator.clipboard){
          const copyBtn=document.createElement('button');copyBtn.type='button';copyBtn.className='goes-copy-btn';copyBtn.textContent='Copiar trama';
          copyBtn.addEventListener('click',()=>{navigator.clipboard.writeText(raw);copyBtn.textContent='¡Copiado!';setTimeout(()=>{copyBtn.textContent='Copiar trama';},1500);});
          badges.append(copyBtn);
        }
        head.append(meta,badges);
        const frame=document.createElement('pre');frame.className='goes-raw-frame';
        if(raw){
          const domsatHeader=raw.slice(0,37),payload=raw.slice(37).replace(/^\r?\n/,'');
          const hSpan=document.createElement('span'),pSpan=document.createElement('span');
          hSpan.className='goes-raw-header';hSpan.textContent='[ENCABEZADO DOMSAT 37B] '+domsatHeader+'\n';
          pSpan.className='goes-raw-payload';pSpan.textContent=payload||'(sin carga útil adicional)';
          frame.append(hSpan,pSpan);
        }else{
          frame.textContent='(Trama cruda no almacenada en este registro; metadatos de recepción arriba)';
        }
        card.append(head,frame);
      }else{
        const missPill=document.createElement('span');missPill.className='goes-pill sig-low';
        missPill.textContent='DCP '+dcpCode+' · Ventana perdida';
        badges.append(missPill);
        head.append(meta,badges);
        card.append(head);
      }
      list.append(card);
    }
  }
  $('query-export').addEventListener('click',async()=>{
    if(!lastQuery)return;$('query-export').disabled=true;
    try{const response=await fetch('/Explore/Export?'+lastQuery);if(!response.ok){let data=await response.json();throw Error(data.error||'No se pudo exportar.');}
      const url=URL.createObjectURL(await response.blob()),link=document.createElement('a');link.href=url;link.download='hydrocloud-'+result.product+(response.headers.get('X-HydroCloud-Truncated')?'‑PARCIAL‑2000':'')+'.csv';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    }catch(error){show(error.message,true);}finally{$('query-export').disabled=false;}
  });
  function renderTable(){const table=document.createElement('table');table.className='cyber-table';const head=document.createElement('thead'),tr=document.createElement('tr');for(const col of result.columns){const th=document.createElement('th');th.textContent=col;tr.append(th);}head.append(tr);table.append(head);const body=document.createElement('tbody');for(const row of result.rows){const tr=document.createElement('tr');for(const col of result.columns){const td=document.createElement('td');td.textContent=row[col]??'—';tr.append(td);}body.append(tr);}table.append(body);$('result-table').replaceChildren(table);}
  const seriesKey=row=>[row.SENSOR_ID,row.VARIABLE,row.DCP_ID,row.TIPO_PERIODO].filter(x=>x!=null).join(' · ')||'Serie';
  const chartColors=['#087f9a','#7c3aed','#dc5a18','#15803d','#c02655','#a16207'];
  const shortSeries=key=>key.replaceAll('_',' ').replace(/\s*·\s*/g,' · ');
  function renderSelectors(){
    const metric=$('chart-metric');metric.replaceChildren();availableSeries=[...new Set(result.rows.map(seriesKey))];selectedSeries=availableSeries.length?[availableSeries[0]]:[];
    for(const col of result.columns.filter(c=>result.rows.some(r=>typeof r[c]==='number')))metric.add(new Option(col,col));
    renderSeriesStrip();
  }
  function renderSeriesStrip(){
    const strip=$('chart-series-strip');strip.replaceChildren();
    for(const key of availableSeries){
      const button=document.createElement('button');button.type='button';button.textContent=shortSeries(key);button.title=shortSeries(key);button.dataset.series=key;button.setAttribute('aria-pressed',String(selectedSeries.includes(key)));if(button.style?.setProperty)button.style.setProperty('--series-color',chartColors[Math.max(0,selectedSeries.indexOf(key))%chartColors.length]);
      button.addEventListener('click',()=>{
        if(chartMode==='single')selectedSeries=[key];
        else if(selectedSeries.includes(key)){if(selectedSeries.length>1)selectedSeries=selectedSeries.filter(item=>item!==key);}
        else if(selectedSeries.length<6)selectedSeries.push(key);
        renderSeriesStrip();draw();
      });strip.append(button);
    }
  }
  function setChartMode(mode){chartMode=mode;if(mode==='single'&&selectedSeries.length>1)selectedSeries=[selectedSeries[0]];$('chart-mode-single').setAttribute('aria-pressed',String(mode==='single'));$('chart-mode-combine').setAttribute('aria-pressed',String(mode==='combine'));renderSeriesStrip();draw();}
  $('chart-mode-single').addEventListener('click',()=>setChartMode('single'));
  $('chart-mode-combine').addEventListener('click',()=>setChartMode('combine'));
  $('chart-metric').addEventListener('change',draw);
  function seriesCatalog(key){const sensorId=key.split(' · ')[0].trim();return (result.series||[]).find(item=>String(item.sensorId).trim()===sensorId)||{sensorId,name:key,unit:'',configuredChartType:'line'};}
  function highstockType(configured){
    const value=String(configured||'line').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
    if(value.includes('column')||value.includes('barra'))return{type:'column'};
    if(value.includes('areaspline')||value.includes('area curva'))return{type:'areaspline'};
    if(value.includes('area'))return{type:'area'};
    if(value.includes('spline')||value.includes('curva'))return{type:'spline'};
    if(value.includes('scatter')||value.includes('punto'))return{type:'scatter'};
    if(value.includes('step')||value.includes('escalon'))return{type:'line',step:'left'};
    return{type:'line'};
  }
  const normalized=value=>String(value||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
  function chartProfile(catalog,shape){
    const text=normalized([catalog.name,catalog.unit,catalog.sensorId].join(' '));
    const profile={kind:'generic',label:'Serie temporal',color:'#087f9a',axisTitle:catalog.unit||'Valor',decimals:2,lineWidth:2,marker:false,axisMin:null,axisMax:null,tickInterval:null};
    if(/nivel (de )?agua|nivel recipiente|tirante|elevacion/.test(text))Object.assign(profile,{kind:'level',label:'Limnigrama',color:'#087f9a',axisTitle:'Nivel'+(catalog.unit?' ('+catalog.unit+')':''),lineWidth:2.2});
    else if(/precipit|lluvia/.test(text))Object.assign(profile,{kind:'rain',label:'Hietograma',color:'#1976a3',axisTitle:'Precipitación'+(catalog.unit?' ('+catalog.unit+')':''),axisMin:0,lineWidth:0,marker:false});
    else if(/corriente/.test(text)&&(/rls|sensor|\bma\b|amp/.test(text)))Object.assign(profile,{kind:'electric',label:'Corriente del sensor',color:'#5d7180',axisTitle:'Corriente'+(catalog.unit?' ('+catalog.unit+')':''),axisMin:0,lineWidth:1.6});
    else if(/caudal|gasto|corriente (del )?agua|velocidad del agua/.test(text))Object.assign(profile,{kind:'flow',label:'Hidrograma',color:'#167c63',axisTitle:(/velocidad/.test(text)?'Velocidad':'Caudal')+(catalog.unit?' ('+catalog.unit+')':''),lineWidth:2.1});
    else if(/temperatura/.test(text))Object.assign(profile,{kind:'temperature',label:'Termograma',color:'#c65332',axisTitle:'Temperatura'+(catalog.unit?' ('+catalog.unit+')':''),lineWidth:1.9});
    else if(/humedad/.test(text))Object.assign(profile,{kind:'humidity',label:'Humedad relativa',color:'#2b7a78',axisTitle:'Humedad relativa'+(catalog.unit?' ('+catalog.unit+')':''),axisMin:0,axisMax:100,lineWidth:1.8});
    else if(/direccion.*(viento|rafaga)|rumbo/.test(text))Object.assign(profile,{kind:'direction',label:'Rumbo del viento',color:'#7656a8',axisTitle:'Dirección (°)',axisMin:0,axisMax:360,tickInterval:90,decimals:0,lineWidth:1.4,marker:true});
    else if(/rafaga/.test(text))Object.assign(profile,{kind:'gust',label:'Ráfagas de viento',color:'#d2691e',axisTitle:'Ráfaga'+(catalog.unit?' ('+catalog.unit+')':''),axisMin:0,lineWidth:1.6});
    else if(/velocidad.*viento|viento/.test(text))Object.assign(profile,{kind:'wind',label:'Anemograma',color:'#bf6a1c',axisTitle:'Velocidad del viento'+(catalog.unit?' ('+catalog.unit+')':''),axisMin:0,lineWidth:1.7});
    else if(/presion/.test(text))Object.assign(profile,{kind:'pressure',label:'Barograma',color:'#4f6690',axisTitle:'Presión'+(catalog.unit?' ('+catalog.unit+')':''),lineWidth:1.8});
    else if(/estado|estatus|bateria|voltaje/.test(text))Object.assign(profile,{kind:'status',label:/bateria|voltaje/.test(text)?'Voltaje de alimentación':'Estado operativo',color:'#607d6c',axisTitle:catalog.unit||'Estado',decimals:1,lineWidth:1.6});
    profile.type=shape.type;profile.step=shape.step||(profile.kind==='status'?'left':undefined);
    return profile;
  }
  function medianInterval(points){const gaps=points.slice(1).map((point,index)=>point.t-points[index].t).filter(gap=>gap>0);if(!gaps.length)return undefined;gaps.sort((a,b)=>a-b);return gaps[Math.floor(gaps.length/2)];}
  const compass=value=>['N','E','S','O','N'][Math.max(0,Math.min(4,Math.round(Number(value)/90)))];
  function draw(){const container=$('series-chart');const legend=$('chart-legend');legend.replaceChildren();const metric=$('chart-metric').value||result.columns.find(column=>result.rows.some(row=>typeof row[column]==='number')),time=result.columns[0];
    const activeSeries=selectedSeries.length?selectedSeries:availableSeries.slice(0,1);
    const groups=activeSeries.map((key,index)=>{const catalog=seriesCatalog(key),shape=highstockType(catalog.configuredChartType),profile=chartProfile(catalog,shape);return{key,catalog,shape,profile,color:chartMode==='single'?profile.color:chartColors[index%chartColors.length],points:result.rows.filter(r=>seriesKey(r)===key&&typeof r[metric]==='number'&&Number.isFinite(Date.parse(r[time]))).map(r=>({t:Date.parse(r[time]),v:r[metric]})).sort((a,b)=>a.t-b.t)};});
    const points=groups.flatMap(group=>group.points);
    for(const group of groups){const item=document.createElement('span'),dot=document.createElement('i'),label=document.createElement('span');if(dot.style?.setProperty)dot.style.setProperty('--series-color',group.color);label.textContent=group.profile.label+' · '+group.catalog.sensorId+' · '+group.catalog.name+(group.catalog.unit?' ('+group.catalog.unit+')':'');item.append(dot,label);legend.append(item);}
    if(!points.length){
      if(stockChart){stockChart.destroy();stockChart=null;}container.replaceChildren();
      $('chart-summary').textContent='No hay valores numéricos para graficar. Revisa la tabla; ausencia de datos no significa cero.';
      if($('kpi-total-obs')) $('kpi-total-obs').textContent = '0';
      if($('kpi-min-val')) $('kpi-min-val').textContent = '—';
      if($('kpi-avg-val')) $('kpi-avg-val').textContent = '—';
      if($('kpi-max-val')) $('kpi-max-val').textContent = '—';
      if($('kpi-sum-val')) $('kpi-sum-val').textContent = '—';
      return;
    }
    const vals=points.map(p=>p.v);
    const min=Math.min(...vals),max=Math.max(...vals),sum=vals.reduce((a,b)=>a+b,0),avg=sum/vals.length;
    if($('kpi-total-obs')) $('kpi-total-obs').textContent = points.length.toLocaleString();
    if($('kpi-min-val')) $('kpi-min-val').textContent = min.toFixed(2);
    if($('kpi-avg-val')) $('kpi-avg-val').textContent = avg.toFixed(2);
    if($('kpi-max-val')) $('kpi-max-val').textContent = max.toFixed(2);
    if($('kpi-sum-val')) $('kpi-sum-val').textContent = sum.toFixed(2);
    const primary=groups[0].profile,isSingle=chartMode==='single'&&groups.length===1;
    const showRainAccumulation=isSingle&&primary.kind==='rain'&&/^(valor|acumulado|acumulado mm|valor medido)$/.test(normalized(metric).replaceAll('_',' '));
    let accumulated=0;
    const accumulatedPoints=showRainAccumulation?groups[0].points.map(point=>[point.t,accumulated+=Math.max(0,point.v)]):[];
    if(showRainAccumulation){const item=document.createElement('span'),dot=document.createElement('i'),label=document.createElement('span');if(dot.style?.setProperty)dot.style.setProperty('--series-color','#8a6d16');label.textContent='Acumulado del periodo · '+accumulated.toFixed(2)+(groups[0].catalog.unit?' '+groups[0].catalog.unit:'');item.append(dot,label);legend.append(item);}
    const axisLabels={style:{color:'#526c74'}};
    if(isSingle&&primary.kind==='direction')axisLabels.formatter=function(){return compass(this.value)+' · '+this.value+'°';};
    const primaryAxis={opposite:false,min:isSingle?primary.axisMin:null,max:isSingle?primary.axisMax:null,tickInterval:isSingle?primary.tickInterval:null,softMin:isSingle&&primary.axisMin===0?0:undefined,title:{text:isSingle?primary.axisTitle:metric,style:{color:'#526c74',fontWeight:'600'}},gridLineColor:'#e1eaec',gridLineDashStyle:'ShortDot',labels:axisLabels};
    const chartAxes=showRainAccumulation?[primaryAxis,{opposite:true,min:0,softMin:0,title:{text:'Acumulado'+(groups[0].catalog.unit?' ('+groups[0].catalog.unit+')':''),style:{color:'#8a6d16',fontWeight:'600'}},gridLineWidth:0,lineWidth:1,lineColor:'#cfbf87',tickColor:'#cfbf87',labels:{style:{color:'#796623'}}}]:primaryAxis;
    const chartSeries=groups.map((group,index)=>({id:'sensor-'+group.catalog.sensorId,name:group.profile.label+' · '+group.catalog.name,type:group.profile.type,step:group.profile.step,color:group.color,lineWidth:group.profile.lineWidth,threshold:group.profile.axisMin===0?0:null,softThreshold:group.profile.axisMin===0,pointRange:group.profile.kind==='rain'?medianInterval(group.points):undefined,marker:{enabled:group.profile.marker||group.profile.type==='scatter',radius:group.profile.kind==='direction'?2.5:3,symbol:'circle'},data:group.points.map(point=>[point.t,point.v]),tooltip:{valueDecimals:group.profile.decimals,valueSuffix:group.catalog.unit?' '+group.catalog.unit:''},showInNavigator:index===0}));
    if(showRainAccumulation)chartSeries.push({id:'rain-accumulated',name:'Acumulado del periodo',type:'line',step:'left',yAxis:1,color:'#8a6d16',lineWidth:2,marker:{enabled:false},data:accumulatedPoints,tooltip:{valueDecimals:2,valueSuffix:groups[0].catalog.unit?' '+groups[0].catalog.unit:''},showInNavigator:false,zIndex:4});
    if(stockChart)stockChart.destroy();
    stockChart=window.Highcharts.stockChart(container,{
      chart:{backgroundColor:'#ffffff',plotBackgroundColor:'#ffffff',animation:false,spacing:[4,6,0,6],style:{fontFamily:'Outfit, Segoe UI, sans-serif'}},
      time:{useUTC:true},title:{text:null},credits:{enabled:true,text:'Highcharts Stock'},
      rangeSelector:{selected:3,inputEnabled:false,labelStyle:{color:'#18323b',fontSize:'11px',fontWeight:'600'},buttons:[{type:'hour',count:6,text:'6 h'},{type:'day',count:1,text:'24 h'},{type:'day',count:3,text:'3 d'},{type:'all',text:'Todo'}],buttonTheme:{width:34,height:18,fill:'#f4f8f9',stroke:'#c5d7dc','stroke-width':1,r:4,style:{color:'#36525b',fontSize:'10px',fontWeight:'600'},states:{hover:{fill:'#e4f1f4',style:{color:'#075f73'}},select:{fill:'#087f9a',style:{color:'#ffffff'}},disabled:{fill:'#f4f6f7',style:{color:'#9aabb0'}}}}},
      navigator:{enabled:true,height:34,margin:5,maskFill:'rgba(8,127,154,.12)',outlineColor:'#a9c0c6',handles:{backgroundColor:'#ffffff',borderColor:'#087f9a'},xAxis:{gridLineColor:'#edf2f3',lineColor:'#b7c9cd',tickColor:'#b7c9cd',labels:{style:{color:'#5b737b',fontSize:'10px'}}},series:{type:'areaspline',color:'#6fa9b5',lineColor:'#6fa9b5',fillColor:'rgba(111,169,181,.16)',fillOpacity:.16}},
      scrollbar:{enabled:true,height:9,barBackgroundColor:'#b7d5db',barBorderColor:'#8eb8c1',buttonBackgroundColor:'#f4f8f9',buttonBorderColor:'#c5d7dc',rifleColor:'#54737b',trackBackgroundColor:'#edf3f4',trackBorderColor:'#d5e2e5'},
      legend:{enabled:false},xAxis:{type:'datetime',lineColor:'#b7c9cd',tickColor:'#b7c9cd',labels:{style:{color:'#526c74'}},crosshair:{color:'#78949b',dashStyle:'ShortDot'},ordinal:false},
      yAxis:chartAxes,
      tooltip:{shared:chartMode==='combine'||showRainAccumulation,xDateFormat:'%e %b %Y, %H:%M UTC',valueDecimals:2,split:false,backgroundColor:'rgba(255,255,255,.98)',borderColor:'#87adb6',borderWidth:1,shadow:true,style:{color:'#18323b',fontSize:'12px'}},
      plotOptions:{series:{animation:false,dataGrouping:{enabled:false},turboThreshold:5000,connectNulls:false,states:{inactive:{opacity:.35},hover:{lineWidthPlus:1}}},column:{pointPadding:.04,groupPadding:.08,borderWidth:0,borderRadius:1,minPointLength:1},area:{fillOpacity:.08},areaspline:{fillOpacity:.08}},
      series:chartSeries
    });
    $('chart-summary').textContent=(showRainAccumulation?'Hietograma + acumulado del periodo':isSingle?primary.label:'Comparación de '+groups.length+' series')+' · '+metric+' · representación configurada en DB_ATLAS · zoom y navegador Highstock.';
  }
})();
