(()=>{
const sidebar=document.querySelector('[data-mobile-sidebar]');
sidebar.restoreNavigation=()=>{
let state;try{state=JSON.parse(sessionStorage.getItem('gstudio.sidebar-navigation.v1'))||{}}catch{state={}}
sidebar.querySelectorAll('.sidebar-section').forEach(node=>{const open=state.sections?.[node.hasAttribute('data-sidebar-favorites')?'favorites':node.dataset.workCategorySection];if(typeof open==='boolean')node.open=open});
const small=innerWidth<=900,top=state[small?'mobile':'desktop'];
if((!small||sidebar.classList.contains('mobile-open'))&&typeof top==='number'&&Number.isFinite(top)&&top>=0)sidebar.querySelector(small?'.sidebar-nav':'.sidebar-nav-main').scrollTop=top;
};sidebar.restoreNavigation();
})();