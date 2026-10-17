/* 全部任务: the home page's read-only task browser. Search, project, type and status filters stay in the
   address bar; rows load in batches inside their own scroll area and open the task. The page renders
   the rows (ember_ui/pages/home.py); mount(root) wires them. Row links may be paths or #hashes. */
(()=>{
function mount(root){
  const params=new URLSearchParams(location.search),batch=50;
  const search=document.getElementById('taskOverviewSearch'),project=document.getElementById('taskOverviewProject'),workType=document.getElementById('taskOverviewType'),chips=document.getElementById('taskOverviewStatus'),clear=document.getElementById('taskOverviewClear'),count=document.getElementById('taskOverviewCount'),scroll=document.getElementById('taskOverviewScroll'),sentinel=document.getElementById('taskOverviewSentinel'),more=document.getElementById('taskOverviewLoadMore'),empty=document.getElementById('taskOverviewEmpty');
  const rows=[...root.querySelectorAll('[data-overview-search]')];
  let limit=batch,status=['all','active','completed','waiting_user','blocked'].includes(params.get('status'))?params.get('status'):'all',matches=rows;
  search.value=params.get('q')||'';project.value=params.get('project')||'';workType.value=params.get('type')||'';
  function syncUrl(){
    const next=new URLSearchParams(location.search);
    search.value.trim()?next.set('q',search.value.trim()):next.delete('q');
    project.value?next.set('project',project.value):next.delete('project');
    workType.value?next.set('type',workType.value):next.delete('type');
    status==='all'?next.delete('status'):next.set('status',status);
    history.replaceState(null,'',location.pathname+(next.size?'?'+next:'')+location.hash);
  }
  function render(reset=false){
    if(reset){limit=batch;scroll.scrollTop=0;}
    const query=search.value.trim().toLowerCase(),projectValue=project.value,typeValue=workType.value;
    matches=rows.filter(row=>(!query||row.dataset.overviewSearch.includes(query))&&(!projectValue||row.dataset.overviewProject===projectValue)&&(!typeValue||row.dataset.overviewType===typeValue)&&(status==='all'||row.dataset.overviewStatus===status));
    rows.forEach(row=>row.classList.add('hidden'));
    matches.slice(0,limit).forEach(row=>row.classList.remove('hidden'));
    const shown=Math.min(limit,matches.length);
    count.textContent=`显示 ${shown} / ${matches.length} 条`;
    sentinel.hidden=shown>=matches.length;
    empty.hidden=matches.length>0;
    scroll.querySelector('table').hidden=matches.length===0;
    chips.querySelectorAll('.chip').forEach(chip=>{const active=chip.dataset.overviewStatusChoice===status;chip.classList.toggle('active',active);chip.setAttribute('aria-pressed',String(active));});
    clear.classList.toggle('dimmed',!(query||projectValue||typeValue||status!=='all'));
    syncUrl();
  }
  function reset(){search.value='';project.value='';workType.value='';status='all';render(true);}
  function loadMore(){if(limit<matches.length){limit+=batch;render();}}
  search.addEventListener('input',()=>render(true));
  [project,workType].forEach(control=>control.addEventListener('change',()=>render(true)));
  chips.addEventListener('click',event=>{const choice=event.target.closest('[data-overview-status-choice]');if(choice){status=choice.dataset.overviewStatusChoice;render(true);}});
  clear.addEventListener('click',reset);root.querySelector('[data-overview-reset]')?.addEventListener('click',()=>{reset();search.focus();});
  more.addEventListener('click',loadMore);
  let observer=null;
  if('IntersectionObserver' in window){observer=new IntersectionObserver(entries=>{if(entries.some(entry=>entry.isIntersecting))loadMore();},{root:scroll,rootMargin:'120px'});observer.observe(sentinel);}
  function openRow(row){if(row.dataset.href.startsWith('#')){location.hash=row.dataset.href;return}const next=new URL(row.dataset.href,location.origin);next.searchParams.set('return_to',location.pathname+location.search+location.hash);location.href=next.pathname+next.search;}
  scroll.addEventListener('click',event=>{const row=event.target.closest('tr[data-href]');if(row&&!event.target.closest('a,button'))openRow(row);});
  scroll.addEventListener('keydown',event=>{const row=event.target.closest('tr[data-href]');if(row&&event.target===row&&(event.key==='Enter'||event.key===' ')){event.preventDefault();openRow(row);}});
  render(true);
  return {destroy(){observer?.disconnect()}};
}
window.EmberTaskOverview={mount};
const root=document.getElementById('homeAllTasks');if(root)mount(root);
})();
