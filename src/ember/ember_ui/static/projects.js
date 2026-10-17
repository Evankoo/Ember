/* Projects view (项目视图): the work-category filter, dragging a task into or out of a project's
   当前重要事项 column, and dragging project cards into a new order. The page renders the markup
   (ember_ui/pages/projects.py); mount(root, options) wires it and returns {destroy}.
   Options (each optional; the defaults are the full workbench's form posts and address hash):
     setPriority({project, taskId, important}) -> Promise   null: tasks cannot be dragged
     saveOrder(slugs) -> Promise                            null: cards cannot be reordered
     saved()            after a successful save (default: reload the page)
     category           {read() -> key, write(key)}; the default keeps the key in the address hash
     notify(message, type) */
(()=>{
const post=(path,body)=>fetch(path,{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded','Accept':'application/json'},body}).then(response=>response.json().then(data=>{if(!response.ok||!data.ok)throw new Error(data.error||'保存失败');return data}));
function mount(root=document,options={}){
  const grid=root.querySelector('.project-view-grid');
  if(!grid)return null;
  const controller=new AbortController(),signal=controller.signal;
  grid.dataset.dragController='single';
  const DRAG_THRESHOLD=6,csrf=options.csrf??grid.dataset.csrf??'';
  const setPriority=options.setPriority===undefined?({project,taskId,important})=>post('/actions/project-priority',new URLSearchParams({csrf,project,task_id:taskId,important:important?'1':'0',return_to:'/projects'})):options.setPriority;
  const saveOrder=options.saveOrder===undefined?slugs=>{const body=new URLSearchParams({csrf,return_to:'/projects'});slugs.forEach(slug=>body.append('project_order',slug));return post('/actions/project-order',body)}:options.saveOrder;
  const saved=options.saved||(()=>location.reload());
  const category=options.category||{read:()=>location.hash.slice(1),write:key=>history.replaceState(null,'',location.pathname+location.search+(key==='all'?'':'#'+key))};
  const notify=options.notify||((message,type='info')=>window.GStudioUI?.toast?.(message,type,5000));
  const categoryButtons=[...root.querySelectorAll('[data-project-category-filter]')];
  const categoryEmpty=root.querySelector('#projectCategoryEmpty');
  function applyCategory(requested){
    const key=categoryButtons.some(button=>button.dataset.projectCategoryFilter===requested)?requested:'all';
    cancelProjectSort();finishTask();grid.dataset.category=key;
    categoryButtons.forEach(button=>{const selected=button.dataset.projectCategoryFilter===key;button.classList.toggle('active',selected);button.setAttribute('aria-pressed',String(selected))});
    let visible=0;
    grid.querySelectorAll('[data-project-card]').forEach(card=>{const show=key==='all'||card.dataset.workCategory===key;card.classList.toggle('hidden',!show);if(show)visible++});
    if(categoryEmpty)categoryEmpty.hidden=visible>0;
  }
  categoryButtons.forEach(button=>button.addEventListener('click',()=>{applyCategory(button.dataset.projectCategoryFilter);category.write(grid.dataset.category)}));
  if(!options.category)window.addEventListener('hashchange',()=>applyCategory(location.hash.slice(1)),{signal});
  const clearColumns=()=>grid.querySelectorAll('.project-view-column').forEach(column=>column.classList.remove('drag-over','return-target','return-blocked'));

  let task=null;
  const finishTask=()=>{task?.classList.remove('dragging');task=null;clearColumns()};
  grid.querySelectorAll('.project-view-task[draggable=true]').forEach(item=>{
    if(!setPriority){item.draggable=false;return}
    item.addEventListener('dragstart',event=>{
      cancelProjectSort();task=item;item.classList.add('dragging');
      event.stopPropagation();event.dataTransfer.effectAllowed='move';event.dataTransfer.setData('text/plain',item.dataset.taskId);
      const source=item.closest('.project-view-column');
      if(source?.dataset.boardColumn==='important'){
        const expected=item.dataset.returnColumn;
        grid.querySelectorAll('.project-view-column').forEach(column=>{
          if(column.dataset.project!==source.dataset.project)return;
          if(expected&&column.dataset.boardColumn===expected)column.classList.add('return-target');
          else if(column.dataset.boardColumn!=='important')column.classList.add('return-blocked');
        });
      }
    });
    item.addEventListener('dragend',finishTask);
  });
  if(setPriority)grid.querySelectorAll('.project-view-column').forEach(column=>{
    const validTarget=()=>{
      if(!task)return false;
      const source=task.closest('.project-view-column');
      if(!source||column.dataset.project!==source.dataset.project||source===column)return false;
      return source.dataset.boardColumn==='important'
        ? Boolean(task.dataset.returnColumn)&&column.dataset.boardColumn===task.dataset.returnColumn
        : column.dataset.boardColumn==='important';
    };
    column.addEventListener('dragover',event=>{if(!validTarget()){event.dataTransfer.dropEffect='none';return}event.preventDefault();event.stopPropagation();event.dataTransfer.dropEffect='move';column.classList.add('drag-over')});
    column.addEventListener('dragleave',event=>{if(!column.contains(event.relatedTarget))column.classList.remove('drag-over')});
    column.addEventListener('drop',event=>{
      if(!validTarget())return;
      event.preventDefault();event.stopPropagation();
      setPriority({project:column.dataset.project,taskId:task.dataset.taskId,important:column.dataset.boardColumn==='important'}).then(()=>saved()).catch(error=>{notify(error.message||'保存失败','error');finishTask()});
    });
  });

  if(!saveOrder)grid.dataset.cardSort='off';
  let pendingCard=null,activeCard=null,marker=null,ghost=null,pointerId=null,startX=0,startY=0,originalCards=[];
  const clearProjectVisual=()=>{
    activeCard?.classList.remove('project-sort-active');
    if(activeCard){activeCard.style.opacity='';activeCard.style.outline=''}
    marker?.remove();ghost?.remove();grid.classList.remove('project-sort-mode');document.body.style.userSelect='';
    marker=null;ghost=null;
  };
  const resetProjectState=()=>{pendingCard=null;activeCard=null;pointerId=null;originalCards=[]};
  function cancelProjectSort(){
    if(originalCards.length)originalCards.forEach(item=>grid.appendChild(item));
    clearProjectVisual();resetProjectState();
  }
  const beginProjectSort=(event)=>{
    activeCard=pendingCard;pendingCard=null;originalCards=[...grid.querySelectorAll('[data-project-card]')];
    marker=document.createElement('div');marker.className='project-sort-placeholder';marker.textContent='放到这里';
    grid.insertBefore(marker,activeCard);activeCard.classList.add('project-sort-active');grid.classList.add('project-sort-mode');
    activeCard.style.opacity='.18';activeCard.style.outline='1px dashed var(--ink)';document.body.style.userSelect='none';
    ghost=document.createElement('div');ghost.className='project-drag-ghost';ghost.textContent=activeCard.dataset.projectTitle;document.body.appendChild(ghost);
    updateProjectSort(event);
  };
  const updateProjectSort=(event)=>{
    if(!activeCard)return;
    ghost.style.left=(event.clientX+16)+'px';ghost.style.top=(event.clientY+16)+'px';
    const targets=[...grid.querySelectorAll('[data-project-card]')].filter(item=>item!==activeCard);
    const before=targets.find(item=>event.clientY<item.getBoundingClientRect().top+item.getBoundingClientRect().height/2);
    grid.insertBefore(marker,before||null);
  };
  const commitProjectSort=()=>{
    if(!activeCard)return;
    grid.insertBefore(activeCard,marker);
    const previous=originalCards.slice(),order=[...grid.querySelectorAll('[data-project-card]')].map(item=>item.dataset.projectCard);
    const unchanged=previous.map(item=>item.dataset.projectCard).join('|')===order.join('|');
    clearProjectVisual();resetProjectState();
    if(unchanged)return;
    saveOrder(order).then(()=>saved()).catch(error=>{previous.forEach(item=>grid.appendChild(item));notify(error.message||'保存失败','error')});
  };
  grid.querySelectorAll('[data-project-card]').forEach(item=>{
    item.draggable=false;
    if(!saveOrder)return;
    item.addEventListener('pointerdown',event=>{
      if(event.button!==0||event.target.closest('.project-view-task,a,button,input,select,textarea,label'))return;
      if(grid.dataset.category!=='all'){notify('筛选分类时不可调整项目顺序；请切回全部。');return}
      finishTask();pendingCard=item;pointerId=event.pointerId;startX=event.clientX;startY=event.clientY;item.setPointerCapture?.(event.pointerId);
    });
  });
  window.addEventListener('pointermove',event=>{
    if(event.pointerId!==pointerId)return;
    if(pendingCard&&Math.hypot(event.clientX-startX,event.clientY-startY)>=DRAG_THRESHOLD)beginProjectSort(event);
    else updateProjectSort(event);
  },{signal});
  window.addEventListener('pointerup',event=>{if(event.pointerId!==pointerId)return;if(activeCard)commitProjectSort();else resetProjectState()},{signal});
  window.addEventListener('pointercancel',cancelProjectSort,{signal});
  window.addEventListener('blur',cancelProjectSort,{signal});
  window.addEventListener('pagehide',cancelProjectSort,{signal});
  applyCategory(category.read());
  return {destroy(){cancelProjectSort();controller.abort()}};
}
window.EmberProjects={mount};
if(document.querySelector('.project-view-grid'))mount();
})();
