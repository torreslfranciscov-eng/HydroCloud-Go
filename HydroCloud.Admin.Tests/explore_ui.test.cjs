// DOM/Leaflet doubles: tests behavior without contacting a map provider or Oracle.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const css=fs.readFileSync(path.join(__dirname,'../HydroCloud.Admin/wwwroot/explore.css'),'utf8');
const signalRule=css.match(/\.map-legend \.signal\{([^}]+)\}/)[1];
for(const declaration of ['padding:0','width:10px','height:10px','flex:0 0 10px'])assert.ok(signalRule.includes(declaration),'Los indicadores deben aislarse del padding global de .empty');
const elements=new Map(),drawn=[];let mapCalls=0,tileCalls=0;
const element=()=>({dataset:{authenticated:'false'},value:'',options:[],children:[],handlers:{},textContent:'',addEventListener(event,callback){this.handlers[event]=callback;},append(...nodes){this.options.push(...nodes);this.children.push(...nodes);},replaceChildren(...nodes){this.options=[];this.children=nodes;this.value='';},add(option){this.options.push(option);if(this.options.length===1)this.value=option.value;},setAttribute(){}});
const document={getElementById(id){assert.notEqual(id,'load-map');if(!elements.has(id))elements.set(id,element());return elements.get(id);},createElement:element,createElementNS(namespace,tag){return {...element(),tag};}};
document.getElementById('map-filter').value='all';
document.getElementById('query-period').value='last7';
const map={setView(){return this;},fitBounds(){},closePopup(){}};
const layer={addTo(){return this;},clearLayers(){drawn.length=0;}};
const L={map(){mapCalls++;return map;},layerGroup(){return layer;},tileLayer(){return{addTo(){tileCalls++;return this;},on(){return this;}};},circleMarker(coords,style){return{bindPopup(){return this;},bindTooltip(node){assert.equal(typeof node,'object');return this;},addTo(){drawn.push(style.fillColor);}};}};
const stations=['a','b','c'].map((id,i)=>({id,name:'Estación '+id,code:id,latitude:17+i,longitude:-93}));
const dataRequests=[];
const context={document,window:{L},L,Date,URLSearchParams,Option:function(text,value){this.text=text;this.value=value;},fetch:async url=>{
  if(url.includes('/Explore/Data?')){
    const query=new URLSearchParams(url.split('?')[1]);dataRequests.push(query);
    if(query.has('start'))return {ok:false,json:async()=>({error:'Selecciona «Últimos 7 días (automático)» o inicia sesión.'})};
    return {ok:true,json:async()=>({rows:[{TS:'2026-09-25T12:00:00Z',SENSOR_ID:'0001',VARIABLE:'nivel',VALOR:1.5}],columns:['TS','SENSOR_ID','VARIABLE','VALOR'],window:{start:'2026-09-18T15:00:00Z',end:'2026-09-25T15:00:00Z'},note:'OK'})};
  }
  return {ok:true,json:async()=>url.includes('Availability')?{checkedAt:new Date().toISOString(),stations:[{stationId:'a',state:'recent'},{stationId:'b',state:'empty'}]}:stations};
}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../HydroCloud.Admin/wwwroot/explore.js'),'utf8'),context);
assert.equal(mapCalls,1);assert.equal(tileCalls,1);
setImmediate(async()=>{
  assert.deepEqual(drawn,['#15803d','#7f1d1d','#64748b']);
  assert.equal(document.getElementById('count-recent').textContent,1);
  assert.equal(document.getElementById('count-empty').textContent,1);
  assert.equal(document.getElementById('count-unknown').textContent,1);
  const filter=document.getElementById('map-filter');filter.value='empty';filter.handlers.change();
  assert.deepEqual(drawn,['#7f1d1d']);
  assert.equal(document.getElementById('query-station').options.length,3);
  console.log('PASS: mapa automático, estados reales, desconocidos grises, conteos, filtro sin duplicados y catálogo conservado.');
  document.getElementById('query-start').value='2000-01-01T00:00'; // stale browser fields must not enter a live request
  document.getElementById('query-end').value='2000-01-08T00:00';
  document.getElementById('query-station').value='a';document.getElementById('query-product').value='variables';
  await document.getElementById('query-form').handlers.submit({preventDefault(){}});
  assert.equal(dataRequests[0].has('start'),false);assert.equal(dataRequests[0].has('end'),false);
  assert.equal(document.getElementById('query-results').hidden,false);
  assert.equal(document.getElementById('query-export').disabled,false);
  assert.equal(document.getElementById('result-table').children.length,1);
  assert.ok(document.getElementById('series-chart').children.some(node=>node.tag==='circle'));
  assert.equal(document.getElementById('query-start').value,'2026-09-18T15:00');
  const period=document.getElementById('query-period');period.value='custom';period.handlers.change();
  assert.equal(document.getElementById('query-start').disabled,false);
  await document.getElementById('query-form').handlers.submit({preventDefault(){}});
  assert.equal(dataRequests[1].has('start'),true);assert.equal(document.getElementById('query-results').hidden,true);
  assert.ok(document.getElementById('query-status').textContent.includes('automático'));
  console.log('PASS: consultar con página antigua genera tabla y gráfica; fechas manuales permanecen sujetas al límite y muestran recuperación.');
});
