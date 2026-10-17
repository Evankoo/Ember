/* System workspace: filters the current and recent tasks as you type. mount(root) wires the page
   rendered by ember_ui/pages/system.py. */
(()=>{
function mount(root=document){const search=root.querySelector('#projectTaskSearch'),list=root.querySelector('#projectTaskList');if(!search||!list)return;const rows=[...list.querySelectorAll('[data-task-search]')];search.addEventListener('input',()=>{const q=search.value.trim().toLowerCase();rows.forEach(row=>row.hidden=!!q&&!row.dataset.taskSearch.includes(q))})}
window.EmberSystem={mount};
if(document.querySelector('.system-task-surface #projectTaskList'))mount();
})();
