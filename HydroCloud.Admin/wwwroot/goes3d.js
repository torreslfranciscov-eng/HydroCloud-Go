/**
 * HydroCloud 3D Satellite Constellation Engine
 * Powered by Three.js & OrbitControls
 * Visualiza la Tierra, GOES-East, GOES-West, transmisiones satelitales y la red de estaciones en 3D.
 */
(() => {
  'use strict';

  let scene, camera, renderer, controls;
  let earthMesh, atmosphereMesh, orbitGroup, stationsGroup, laserGroup, starfield;
  let isInitialized = false, isRunning = false, animationFrameId = null;
  let raycaster, mouse;
  let interactivePoints = [];
  let satelliteEast, satelliteWest;
  let currentTargetStation = null;

  const EARTH_RADIUS = 50;
  const SATELLITE_ORBIT_RADIUS = 115;
  const GOES_EAST_LON = -75.2;
  const GOES_WEST_LON = -137.2;

  // Convertir coordenadas Lat/Lon a Vector3 en esfera
  function latLonToVector3(lat, lon, radius) {
    const phi = (90 - lat) * (Math.PI / 180);
    const theta = (lon + 180) * (Math.PI / 180);
    const x = -(radius * Math.sin(phi) * Math.cos(theta));
    const z = (radius * Math.sin(phi) * Math.sin(theta));
    const y = (radius * Math.cos(phi));
    return new THREE.Vector3(x, y, z);
  }

  // Generador de textura procedural para la Tierra (Océanos azul profundo + Continentes con bordes cian neón)
  function createProceduralEarthTexture() {
    const canvas = document.createElement('canvas');
    canvas.width = 2048;
    canvas.height = 1024;
    const ctx = canvas.getContext('2d');

    // Fondo oceánico profundo con gradiente
    const oceanGrad = ctx.createLinearGradient(0, 0, 0, 1024);
    oceanGrad.addColorStop(0, '#06131d');
    oceanGrad.addColorStop(0.5, '#0a2233');
    oceanGrad.addColorStop(1, '#06131d');
    ctx.fillStyle = oceanGrad;
    ctx.fillRect(0, 0, 2048, 1024);

    // Rejilla de coordenadas (Latitud / Longitud)
    ctx.strokeStyle = 'rgba(14, 165, 233, 0.12)';
    ctx.lineWidth = 1;
    for (let x = 0; x <= 2048; x += 2048 / 24) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, 1024);
      ctx.stroke();
    }
    for (let y = 0; y <= 1024; y += 1024 / 12) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(2048, y);
      ctx.stroke();
    }

    // Dibujar continentes estilizados (Proyección Equirrectangular)
    // Coordenadas x = (lon + 180) * (2048 / 360), y = (90 - lat) * (1024 / 180)
    function toCanvas(lon, lat) {
      return [(lon + 180) * (2048 / 360), (90 - lat) * (1024 / 180)];
    }

    ctx.fillStyle = '#112b3c';
    ctx.strokeStyle = '#00f0ff';
    ctx.lineWidth = 1.5;

    // Silueta simplificada de las Américas
    const americas = [
      // Norteamérica
      [[-165, 68], [-140, 70], [-100, 72], [-65, 60], [-55, 50], [-70, 42], [-75, 35], [-80, 25], [-82, 23],
       // México
       [-97, 26], [-97, 22], [-90, 21], [-87, 21], [-87, 18], [-93, 16], [-96, 16], [-105, 20], [-105, 23],
       [-110, 24], [-115, 30], [-117, 32], [-124, 40], [-125, 48], [-130, 54], [-140, 60], [-160, 58], [-165, 68]],
      // Baja California
      [[-114, 32], [-115, 29], [-112, 26], [-110, 23], [-110, 24], [-112, 28], [-114, 32]],
      // Península de Yucatán
      [[-90, 21], [-87, 21], [-87, 18], [-90, 18], [-90, 21]],
      // Sudamérica
      [[-77, 8], [-60, 10], [-50, 0], [-35, -5], [-35, -10], [-40, -22], [-50, -30], [-55, -38], [-65, -55],
       [-72, -53], [-75, -45], [-72, -35], [-70, -20], [-80, -5], [-80, 2], [-77, 8]]
    ];

    americas.forEach(poly => {
      ctx.beginPath();
      poly.forEach(([lon, lat], i) => {
        const [cx, cy] = toCanvas(lon, lat);
        if (i === 0) ctx.moveTo(cx, cy);
        else ctx.lineTo(cx, cy);
      });
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
    });

    // Brillo especial en el contorno de México
    ctx.strokeStyle = '#38bdf8';
    ctx.lineWidth = 2.5;
    ctx.shadowColor = '#00f0ff';
    ctx.shadowBlur = 8;
    const mexicoContour = [
      [-117, 32.5], [-114.5, 31.8], [-111, 31.3], [-108.2, 31.8], [-106.5, 31.8], [-104.5, 29.5],
      [-102, 29], [-100, 28], [-99, 26], [-97.5, 26], [-97, 22], [-93, 18.5], [-91, 18],
      [-90.5, 19.8], [-90, 21.4], [-87, 21.4], [-86.8, 18.2], [-88.3, 18.2], [-89, 17.8],
      [-91, 17.5], [-92.2, 14.5], [-93, 15.8], [-96, 16], [-100, 16.8], [-105, 19.8],
      [-105.5, 22.8], [-109, 25.5], [-112, 28.5], [-115, 31], [-117, 32.5]
    ];
    ctx.beginPath();
    mexicoContour.forEach(([lon, lat], i) => {
      const [cx, cy] = toCanvas(lon, lat);
      if (i === 0) ctx.moveTo(cx, cy);
      else ctx.lineTo(cx, cy);
    });
    ctx.stroke();

    const texture = new THREE.CanvasTexture(canvas);
    texture.wrapS = THREE.RepeatWrapping;
    texture.wrapT = THREE.ClampToEdgeWrapping;
    return texture;
  }

  // Crear modelo 3D de Satélite GOES
  function createGoesSatelliteModel(name, color = '#f59e0b') {
    const group = new THREE.Group();

    // Cuerpo principal cúbico
    const bodyGeo = new THREE.BoxGeometry(2.5, 2.5, 3.5);
    const bodyMat = new THREE.MeshStandardMaterial({
      color: 0x22323d,
      metalness: 0.8,
      roughness: 0.2,
      emissive: 0x051b24,
      emissiveIntensity: 0.5
    });
    const body = new THREE.Mesh(bodyGeo, bodyMat);
    group.add(body);

    // Paneles solares extendidos
    const panelGeo = new THREE.BoxGeometry(10, 2, 0.15);
    const panelMat = new THREE.MeshStandardMaterial({
      color: 0x0a3356,
      metalness: 0.9,
      roughness: 0.1,
      emissive: 0x002244
    });
    const panel = new THREE.Mesh(panelGeo, panelMat);
    panel.position.set(0, 0, 0);
    group.add(panel);

    // Antena parabólica apuntando a la Tierra
    const dishGeo = new THREE.ConeGeometry(1.6, 1, 16, 1, true);
    const dishMat = new THREE.MeshStandardMaterial({
      color: 0xffffff,
      metalness: 0.5,
      roughness: 0.3,
      side: THREE.DoubleSide
    });
    const dish = new THREE.Mesh(dishGeo, dishMat);
    dish.rotation.x = Math.PI;
    dish.position.set(0, -1.8, 0);
    group.add(dish);

    // Faro de luz / baliza
    const beaconGeo = new THREE.SphereGeometry(0.5, 12, 12);
    const beaconMat = new THREE.MeshBasicMaterial({ color: color });
    const beacon = new THREE.Mesh(beaconGeo, beaconMat);
    beacon.position.set(0, 2, 0);
    group.add(beacon);

    // Cono de cobertura hacia la Tierra (onda translúcida)
    const coneGeo = new THREE.ConeGeometry(32, 60, 32, 1, true);
    const coneMat = new THREE.MeshBasicMaterial({
      color: 0x38bdf8,
      transparent: true,
      opacity: 0.08,
      wireframe: true,
      side: THREE.DoubleSide
    });
    const cone = new THREE.Mesh(coneGeo, coneMat);
    cone.position.set(0, -32, 0);
    group.add(cone);

    group.name = name;
    return group;
  }

  // Inicializar Escena 3D
  function init3D() {
    if (isInitialized) return;
    const container = document.getElementById('goes-3d-container');
    const canvas = document.getElementById('goes-3d-canvas');
    if (!container || !canvas) return;

    const width = container.clientWidth || 900;
    const height = container.clientHeight || 560;

    // Escena
    scene = new THREE.Scene();
    scene.fog = new THREE.FogExp2(0x030b12, 0.0018);

    // Cámara
    camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 2000);
    const startPos = latLonToVector3(15, -102, 220);
    camera.position.copy(startPos);

    // Renderizador WebGL
    renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true, alpha: true });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));

    // Controles de Órbita
    controls = new THREE.OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.05;
    controls.minDistance = 65;
    controls.maxDistance = 500;
    controls.target.set(0, 0, 0);

    // Luces
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.7);
    scene.add(ambientLight);

    const sunLight = new THREE.DirectionalLight(0xffffff, 1.2);
    sunLight.position.set(200, 100, 200);
    scene.add(sunLight);

    // Campo de Estrellas (Starfield galáctico)
    const starGeo = new THREE.BufferGeometry();
    const starCount = 1800;
    const starPositions = new Float32Array(starCount * 3);
    for (let i = 0; i < starCount * 3; i += 3) {
      starPositions[i] = (Math.random() - 0.5) * 1600;
      starPositions[i + 1] = (Math.random() - 0.5) * 1600;
      starPositions[i + 2] = (Math.random() - 0.5) * 1600;
    }
    starGeo.setAttribute('position', new THREE.BufferAttribute(starPositions, 3));
    const starMat = new THREE.PointsMaterial({ color: 0x94a3b8, size: 1.6, transparent: true, opacity: 0.65 });
    starfield = new THREE.Points(starGeo, starMat);
    scene.add(starfield);

    // Malla de la Tierra
    const earthGeo = new THREE.SphereGeometry(EARTH_RADIUS, 64, 64);
    const earthTexture = createProceduralEarthTexture();
    const earthMat = new THREE.MeshStandardMaterial({
      map: earthTexture,
      roughness: 0.7,
      metalness: 0.1,
      bumpScale: 0.05
    });
    earthMesh = new THREE.Mesh(earthGeo, earthMat);
    scene.add(earthMesh);

    // Resplandor atmosférico exterior
    const atmosGeo = new THREE.SphereGeometry(EARTH_RADIUS * 1.03, 48, 48);
    const atmosMat = new THREE.MeshBasicMaterial({
      color: 0x38bdf8,
      transparent: true,
      opacity: 0.14,
      side: THREE.BackSide,
      blending: THREE.AdditiveBlending
    });
    atmosphereMesh = new THREE.Mesh(atmosGeo, atmosMat);
    scene.add(atmosphereMesh);

    // Anillo de Órbita Geoestacionaria (Línea dorada)
    const orbitCurve = new THREE.EllipseCurve(0, 0, SATELLITE_ORBIT_RADIUS, SATELLITE_ORBIT_RADIUS, 0, 2 * Math.PI, false, 0);
    const orbitPoints = orbitCurve.getPoints(120);
    const orbitGeo = new THREE.BufferGeometry().setFromPoints(orbitPoints.map(p => new THREE.Vector3(p.x, 0, p.y)));
    const orbitMat = new THREE.LineBasicMaterial({ color: 0xfacc15, transparent: true, opacity: 0.35, linewidth: 1.5 });
    const orbitLine = new THREE.Line(orbitGeo, orbitMat);
    scene.add(orbitLine);

    // Satélites GOES-East y GOES-West
    satelliteEast = createGoesSatelliteModel('GOES-East (16)', '#38bdf8');
    const posEast = latLonToVector3(0, GOES_EAST_LON, SATELLITE_ORBIT_RADIUS);
    satelliteEast.position.copy(posEast);
    satelliteEast.lookAt(0, 0, 0);
    scene.add(satelliteEast);

    satelliteWest = createGoesSatelliteModel('GOES-West (18)', '#a855f7');
    const posWest = latLonToVector3(0, GOES_WEST_LON, SATELLITE_ORBIT_RADIUS);
    satelliteWest.position.copy(posWest);
    satelliteWest.lookAt(0, 0, 0);
    scene.add(satelliteWest);

    // Grupos para estaciones y láseres de telemetría
    stationsGroup = new THREE.Group();
    scene.add(stationsGroup);

    laserGroup = new THREE.Group();
    scene.add(laserGroup);

    // Raycaster para interactividad
    raycaster = new THREE.Raycaster();
    mouse = new THREE.Vector2();

    canvas.addEventListener('mousemove', on3DMouseMove);
    canvas.addEventListener('click', on3DMouseClick);
    window.addEventListener('resize', on3DResize);

    isInitialized = true;
  }

  // Trazar estaciones en la esfera 3D
  function plotStationsOn3D(stationsList) {
    if (!stationsGroup) return;

    // Limpiar anteriores
    while (stationsGroup.children.length > 0) {
      stationsGroup.remove(stationsGroup.children[0]);
    }
    while (laserGroup.children.length > 0) {
      laserGroup.remove(laserGroup.children[0]);
    }
    interactivePoints = [];

    const list = stationsList || window.hydroCatalogStations || [];
    const countEl = document.getElementById('hud-3d-stations-count');
    if (countEl) countEl.textContent = list.length;

    // Materiales compartidos
    const matOk = new THREE.MeshBasicMaterial({ color: 0x16a34a });
    const matLate = new THREE.MeshBasicMaterial({ color: 0xd97706 });
    const matOffline = new THREE.MeshBasicMaterial({ color: 0xdc2626 });
    const matUser = new THREE.MeshBasicMaterial({ color: 0xfacc15 });
    const pinGeo = new THREE.SphereGeometry(0.55, 10, 10);
    const userPinGeo = new THREE.SphereGeometry(0.95, 12, 12);

    list.forEach(st => {
      if (st.latitude == null || st.longitude == null) return;
      const isUser = Boolean(st.userId);
      const isOk = !st.state || st.state === 'recent';
      const isLate = st.state === 'week';

      const mat = isUser ? matUser : (isOk ? matOk : (isLate ? matLate : matOffline));
      const geo = isUser ? userPinGeo : pinGeo;
      const mesh = new THREE.Mesh(geo, mat);

      const pos = latLonToVector3(st.latitude, st.longitude, EARTH_RADIUS + 0.4);
      mesh.position.copy(pos);
      mesh.userData = st;

      stationsGroup.add(mesh);
      interactivePoints.push(mesh);
    });

    // Crear haces láser de telemetría desde 12 estaciones clave hacia GOES-East
    const targetSatPos = satelliteEast.position;
    const sampledStations = list.filter((_, i) => i % 60 === 0).slice(0, 10);

    sampledStations.forEach(st => {
      if (!st.latitude || !st.longitude) return;
      const startPos = latLonToVector3(st.latitude, st.longitude, EARTH_RADIUS + 0.5);

      // Curva Bezier hacia el satélite
      const midPoint = new THREE.Vector3().addVectors(startPos, targetSatPos).multiplyScalar(0.5);
      midPoint.multiplyScalar(1.2); // Levantar el arco

      const curve = new THREE.QuadraticBezierCurve3(startPos, midPoint, targetSatPos);
      const points = curve.getPoints(40);
      const curveGeo = new THREE.BufferGeometry().setFromPoints(points);

      const curveMat = new THREE.LineDashedMaterial({
        color: 0x38bdf8,
        dashSize: 3,
        gapSize: 2,
        transparent: true,
        opacity: 0.55
      });

      const line = new THREE.Line(curveGeo, curveMat);
      line.computeLineDistances();
      laserGroup.add(line);
    });
  }

  // Interacción de ratón
  function on3DMouseMove(event) {
    const rect = event.target.getBoundingClientRect();
    mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

    raycaster.setFromCamera(mouse, camera);
    const intersects = raycaster.intersectObjects(interactivePoints);

    const targetNameEl = document.getElementById('hud-3d-target-name');
    const targetDetailsEl = document.getElementById('hud-3d-target-details');

    if (intersects.length > 0) {
      const st = intersects[0].object.userData;
      if (targetNameEl) targetNameEl.textContent = `${st.name || 'Estación'} (${st.code})`;
      if (targetDetailsEl) {
        targetDetailsEl.textContent = `Lat: ${st.latitude.toFixed(4)}° · Lon: ${st.longitude.toFixed(4)}° · ${st.userId ? '⭐ Mi Estación GOES' : (st.isDam ? 'Presa' : 'Estación Hidrométrica')}`;
      }
      document.body.style.cursor = 'pointer';
    } else {
      document.body.style.cursor = 'default';
    }
  }

  function on3DMouseClick(event) {
    const rect = event.target.getBoundingClientRect();
    mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

    raycaster.setFromCamera(mouse, camera);
    const intersects = raycaster.intersectObjects(interactivePoints);

    if (intersects.length > 0) {
      const st = intersects[0].object.userData;
      currentTargetStation = st;
      // Animar cámara hacia la estación
      const targetPos = latLonToVector3(st.latitude, st.longitude, EARTH_RADIUS + 35);
      animateCameraTo(targetPos, new THREE.Vector3(0, 0, 0));
    }
  }

  // Animación fluida de cámara
  function animateCameraTo(targetCamPos, targetLookAt) {
    if (typeof anime === 'function') {
      anime({
        targets: camera.position,
        x: targetCamPos.x,
        y: targetCamPos.y,
        z: targetCamPos.z,
        duration: 1200,
        easing: 'easeOutCubic'
      });
      anime({
        targets: controls.target,
        x: targetLookAt.x,
        y: targetLookAt.y,
        z: targetLookAt.z,
        duration: 1200,
        easing: 'easeOutCubic'
      });
    } else {
      camera.position.copy(targetCamPos);
      controls.target.copy(targetLookAt);
    }
  }

  function on3DResize() {
    const container = document.getElementById('goes-3d-container');
    if (!container || !renderer || !camera) return;
    const width = container.clientWidth || 900;
    const height = container.clientHeight || 560;
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    renderer.setSize(width, height);
  }

  // Bucle de renderizado
  function animate() {
    if (!isRunning) return;
    animationFrameId = requestAnimationFrame(animate);

    // Rotación suave del globo si no se está interactuando fuertemente
    if (earthMesh) {
      earthMesh.rotation.y += 0.0004;
      if (atmosphereMesh) atmosphereMesh.rotation.y += 0.0004;
      if (stationsGroup) stationsGroup.rotation.y += 0.0004;
      if (laserGroup) laserGroup.rotation.y += 0.0004;
    }

    // Pequeño movimiento orbital del satélite
    if (satelliteEast) satelliteEast.rotation.y += 0.005;
    if (satelliteWest) satelliteWest.rotation.y += 0.005;

    controls.update();
    renderer.render(scene, camera);
  }

  // API pública
  window.openGoes3DModal = function (stations) {
    const dialog = document.getElementById('goes-3d-dialog');
    if (!dialog) return;

    if (!isInitialized) {
      init3D();
    }
    plotStationsOn3D(stations);

    dialog.showModal();
    isRunning = true;
    on3DResize();
    animate();

    // Default focus: Órbita Global
    focusGlobal();
  };

  window.closeGoes3DModal = function () {
    const dialog = document.getElementById('goes-3d-dialog');
    if (dialog) dialog.close();
    isRunning = false;
    if (animationFrameId) cancelAnimationFrame(animationFrameId);
  };

  function focusMexico() {
    const pos = latLonToVector3(23, -102, EARTH_RADIUS + 75);
    animateCameraTo(pos, new THREE.Vector3(0, 0, 0));
    setActiveNavBtn('btn-3d-nav-mexico');
  }

  function focusGoesEast() {
    const pos = latLonToVector3(5, GOES_EAST_LON, SATELLITE_ORBIT_RADIUS + 45);
    pos.x += 15;
    animateCameraTo(pos, satelliteEast.position);
    setActiveNavBtn('btn-3d-nav-goeseast');
  }

  function focusGoesWest() {
    const pos = latLonToVector3(5, GOES_WEST_LON, SATELLITE_ORBIT_RADIUS + 45);
    pos.x -= 15;
    animateCameraTo(pos, satelliteWest.position);
    setActiveNavBtn('btn-3d-nav-goeswest');
  }

  function focusGlobal() {
    const pos = latLonToVector3(15, -102, 220);
    animateCameraTo(pos, new THREE.Vector3(0, 0, 0));
    setActiveNavBtn('btn-3d-nav-global');
  }

  function setActiveNavBtn(id) {
    document.querySelectorAll('.btn-3d-nav').forEach(b => b.classList.remove('active'));
    document.getElementById(id)?.classList.add('active');
  }

  // Listeners de UI
  document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('btn-open-3d-globe')?.addEventListener('click', () => {
      window.openGoes3DModal(window.stations || []);
    });
    document.getElementById('close-3d-dialog')?.addEventListener('click', window.closeGoes3DModal);
    document.getElementById('btn-3d-nav-mexico')?.addEventListener('click', focusMexico);
    document.getElementById('btn-3d-nav-goeseast')?.addEventListener('click', focusGoesEast);
    document.getElementById('btn-3d-nav-goeswest')?.addEventListener('click', focusGoesWest);
    document.getElementById('btn-3d-nav-global')?.addEventListener('click', focusGlobal);
  });

})();

