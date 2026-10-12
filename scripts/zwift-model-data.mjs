// Offline generator: node scripts/zwift-model-data.mjs <zwift-data> <zwift-bikes>
// Inputs must be the pinned revisions recorded in model.json.
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {gzipSync} from 'node:zlib';
import {execFileSync} from 'node:child_process';
const [dataRoot, modelRoot] = process.argv.slice(2);
const dataCommit = '1025596dce5b7b3c076e84c02e85e8ca3ab4acc4';
const modelCommit = '8a8952f3138ad45fb4f0f3bfbf2bcab73f758a44';
for (const [root, commit] of [[dataRoot, dataCommit], [modelRoot, modelCommit]]) {
  if (execFileSync('git', ['-C', root, 'rev-parse', 'HEAD'], {encoding:'utf8'}).trim() !== commit) throw Error('Wrong input revision');
}
const {routes} = await import(pathToFileURL(path.join(dataRoot, 'src/routes.ts')));
const polygons = JSON.parse(fs.readFileSync(path.join(modelRoot, 'shared/data/zwiftmapSurfacePolygons.json')));
function inside([x,y], ring) {
  let yes = false;
  for (let i=0,j=ring.length-1;i<ring.length;j=i++) {
    const [xi,yi]=ring[i], [xj,yj]=ring[j];
    if ((yi>y)!==(yj>y) && x<(xj-xi)*(y-yi)/(yj-yi)+xi) yes=!yes;
  }
  return yes;
}
const output={};
for (const route of routes.filter(r=>r.sports.includes('cycling'))) {
  const row={name:route.name, slug:route.slug, distance:route.distance*1000, ascent:route.elevation,
    lead_distance:route.leadInDistance*1000, lead_ascent:route.leadInElevation, lap:route.lap};
  const file=path.join(dataRoot, 'src/streams/routes', route.slug+'.ts');
  if (fs.existsSync(file)) {
    const stream=await import(pathToFileURL(file));
    const d=stream.distance, a=stream.altitude, xy=stream.latlng;
    const span=d.at(-1)-d[0];
    // Reject badly aligned Strava segments, rather than stretching the wrong course.
    if (d.length===a.length && d.length===xy.length && span>0 && Math.abs(span/row.distance-1)<0.1) {
      const points=[];
      let prev=0;
      for (let i=1;i<d.length;i++) {
        if (d[i]-d[prev]<25 && i!==d.length-1) continue;
        if (d[i]<=d[prev]) continue;
        const surface=(polygons[route.world]||[]).find(p=>inside(xy[i],p.polygon))?.type||'tarmac';
        points.push([+( (d[i]-d[prev])*row.distance/span ).toFixed(4), +( (a[i]-a[prev]) ).toFixed(4), surface]);
        prev=i;
      }
      row.segments=points;
    }
  }
  output[String(route.id)]=row;
}
const destination='apps/lambda/python/3.14/zwift-calendar/zwift_calendar/data';
fs.writeFileSync(destination+'/routes.json.gz',gzipSync(JSON.stringify({version:1,commit:dataCommit,routes:output}),{level:9}));
fs.writeFileSync(destination+'/model.json',JSON.stringify({version:1,commit:modelCommit,gravity:9.80665,air_density:1.225,efficiency:0.975,bike_mass:8,equipment_cda:0.32,crr:{tarmac:.004,brick:.0055,wood:.0065,cobbles:.0065,snow:.0055,dirt:.016,grass:.025,sand:.004,gravel:.012}},null,2)+'\n');
for (const [root,name] of [[dataRoot,'zwift-data'],[modelRoot,'zwift-bikes']]) fs.copyFileSync(path.join(root,'LICENSE'),destination+'/'+name+'-LICENSE');
fs.copyFileSync(path.join(modelRoot,'THIRD_PARTY_NOTICES.md'), destination+'/upstream-NOTICES.md');
console.log(JSON.stringify({routes:Object.keys(output).length,profiles:Object.values(output).filter(r=>r.segments).length}));
