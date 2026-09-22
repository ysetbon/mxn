const byId = id => document.getElementById(id);
const API = ['127.0.0.1','localhost'].includes(location.hostname)?'':'http://127.0.0.1:5174';
async function jev(body) {
  const response=await fetch(API+'/api/jev',{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:undefined,body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(10000)});
  const data=await response.json();if(!response.ok)throw Error(data.error||'Could not update Jev settings');return data;
}
function show(s,error){
  const note=byId('jev-status');note.classList.toggle('error',!!error);
  if(error){note.textContent=error;return;}
  const where={saved:'saved on this computer',session:'kept until the renderer restarts',environment:'from TYPESAFE_API_KEY'}[s.source];
  note.textContent=!s.configured?'No key yet · alignment uses the full search':`Key …${s.hint||'••••'} ${where}${s.enabled?' · Jev is on':' · Jev is off'}${s.sdk?'':' · install typesafe-sdk to use it'}`;
  byId('jev-enabled').checked=s.enabled;byId('jev-remember').checked=s.remember;byId('jev-forget').hidden=s.source!=='saved'&&s.source!=='session';
}
async function update(body){try{show(await jev(body));}catch(e){show(null,e.message);}}
window.refreshJev=()=>update();
byId('jev-save').onclick=()=>{const key=byId('jev-key').value.trim();if(!key){show(null,'Paste your Jev key first.');return;}byId('jev-key').value='';update({apiKey:key,enabled:true,remember:byId('jev-remember').checked});};
byId('jev-enabled').onchange=e=>update({enabled:e.target.checked});
byId('jev-remember').onchange=e=>update({remember:e.target.checked});
byId('jev-forget').onclick=()=>update({forget:true});
update();
