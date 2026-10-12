// Produce reference outputs by executing the pinned upstream TypeScript itself.
// node scripts/zwift-force-reference.mjs /path/to/pinned/zwift-bikes
import fs from 'node:fs';
import {stripTypeScriptTypes} from 'node:module';
import {execFileSync} from 'node:child_process';
const root=process.argv[2];
const commit='8a8952f3138ad45fb4f0f3bfbf2bcab73f758a44';
if(execFileSync('git',['-C',root,'rev-parse','HEAD'],{encoding:'utf8'}).trim()!==commit) throw Error('Wrong reference revision');
let source=fs.readFileSync(root+'/shared/utils/physics/forces.ts','utf8').replace(/^import .*$/gm,'');
const surfaces=fs.readFileSync(root+'/shared/data/surfaceCrr.ts','utf8');
source=surfaces.slice(surfaces.indexOf('export const SURFACE_CRR'),surfaces.indexOf('export function normalizeSurfaceComposition'))+source;
const equipment=fs.readFileSync(root+'/shared/utils/physics/equipment.ts','utf8');
source+=equipment.slice(equipment.indexOf('export function riderFrontalAreaM2'),equipment.indexOf('// --- Solve absolute'));
source='const BASE_EQUIPMENT_CDA = 0.32;\n'+source;
const model=await import('data:text/javascript;base64,'+Buffer.from(stripTypeScriptTypes(source)).toString('base64'));
const cases=[];
for(const [v,grade,power,weight,height,surface] of [[0,0,100,75,183,'tarmac'],[10,0,250,75,183,'tarmac'],[4,.08,200,90,190,'dirt'],[18,-.08,100,60,160,'cobbles'],[8,.03,0,75,175,'snow']]) {
  const cda=model.riderScaledCdaM2(.32,height,weight);
  const force=model.calculateForces(v,grade,{weightKg:weight,heightCm:height,powerW:power},{bikeMassKg:8,cdaM2:cda},surface,'road');
  cases.push({v,grade,power,weight,height,surface,cda,forces:Object.values(force),speed:model.speedForPower(power,weight+8,grade,model.rollingResistanceCoefficient(surface,'road'),cda)});
}
fs.writeFileSync('apps/lambda/python/3.14/zwift-calendar/tests/fixtures/force-reference.json',JSON.stringify({commit,cases},null,2)+'\n');
