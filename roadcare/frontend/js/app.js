const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=d=>d?new Date(d).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'}):'';
async function api(path,o={}){const m=o.method||'GET',h={...(o.headers||{})};
  if(m!=='GET')h['X-CSRFToken']=(await (await fetch('/api/csrf')).json()).token;
  if(o.json){h['Content-Type']='application/json';o.body=JSON.stringify(o.json)}
  const r=await fetch(path,{...o,method:m,headers:h}),d=await r.json().catch(()=>({}));
  if(r.status===401&&!path.includes('login')){location='/'+(location.pathname.includes('admin')?'admin':'user')+'-login.html'}
  if(!r.ok){const e=new Error(d.error||'Request failed');e.data=d;throw e}return d}
function toast(msg,ok=true){let w=document.getElementById('tw');if(!w){w=document.createElement('div');w.id='tw';w.className='toast-container position-fixed top-0 end-0 p-3';document.body.append(w)}
  const t=document.createElement('div');t.className='toast align-items-center text-bg-'+(ok?'success':'danger')+' border-0 show';t.innerHTML='<div class="d-flex"><div class="toast-body">'+esc(msg)+'</div></div>';w.append(t);setTimeout(()=>t.remove(),4000)}
const badge=s=>`<span class="badge-s s-${esc(s)}">${esc(s)}</span>`;
async function shell(role,active){const me=await api('/api/me');if(role!=='any'&&me.role!==role){location='/'+role+'-login.html';return}
  const N={user:[['user-dashboard','speedometer2','Dashboard'],['submit-complaint','plus-circle','Report damage'],['my-complaints','list-check','My complaints'],['notifications','bell','Notifications'],['messages','envelope','Messages'],['profile','person','Profile']],
  admin:[['admin-dashboard','speedometer2','Operations'],['admin-complaints','inboxes','Complaints'],['admin-maintenance','cone-striped','Maintenance queue'],['admin-messages','envelope','Messages'],['admin-analytics','bar-chart','Analytics']]}[me.role];
  const cur=N.find(n=>n[0]===active),unread=me.role==='user'?(await api('/api/notifications')).unread:0;
  document.body.insertAdjacentHTML('afterbegin',`<aside class="rc-side" id="side"><div class="brand"><i class="bi bi-cone-striped"></i>RoadCare</div>${N.map(n=>`<a href="/${n[0]}.html" class="${n[0]===active?'active':''}"><i class="bi bi-${n[1]}"></i>${n[2]}</a>`).join('')}
  ${me.role==='admin'?'<a href="/api/admin/export.csv"><i class="bi bi-download"></i>Export CSV</a>':''}</aside>
  <div class="rc-main"><div class="rc-top"><button class="btn d-md-none" onclick="side.classList.toggle('open')" aria-label="Menu"><i class="bi bi-list"></i></button><span class="text-muted small">${me.role==='admin'?'Administration':'Citizen portal'}</span>
  <div>${me.role==='user'?`<a href="/notifications.html" class="btn btn-sm position-relative" title="Notifications" aria-label="Notifications"><i class="bi bi-bell"></i>${unread?`<span class="badge bg-danger position-absolute top-0 start-50">${unread}</span>`:''}</a>`:''}${esc(me.name)} <button class="btn btn-sm btn-outline-secondary ms-2" id="lo">Sign out</button></div></div>
  <div class="rc-body"><nav class="small text-muted mb-3">RoadCare / ${esc(cur?cur[2]:'Details')}</nav><div id="main"></div></div></div>`);
  document.getElementById('lo').onclick=async()=>{await api('/api/logout',{method:'POST'});location='/'};return me}
async function doLogin(e,role){e.preventDefault();const f=e.target;
  try{await api('/api/login',{method:'POST',json:{email:f.email.value,password:f.password.value,role}});location='/'+role+'-dashboard.html'}catch(x){toast(x.message,false)}}
