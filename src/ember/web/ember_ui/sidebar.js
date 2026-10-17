/* Sidebar navigation state: remembers which sections are open and where each
   navigation list was scrolled, and opens or closes the sidebar on small
   screens. sidebar-state.js restores the saved state as soon as the sidebar is
   parsed; this file saves it. Sections are looked up on every save so a sidebar
   whose project list is re-rendered keeps working. */
(()=>{
  const sidebar=document.querySelector('[data-mobile-sidebar]');if(!sidebar)return;
  const toggle=sidebar.querySelector('.sidebar-mobile-toggle');
  const desktop=sidebar.querySelector('.sidebar-nav-main'),mobile=sidebar.querySelector('.sidebar-nav'),key='gstudio.sidebar-navigation.v1';
  const sectionKey=node=>node.hasAttribute('data-sidebar-favorites')?'favorites':node.dataset.workCategorySection;
  function read(){try{const value=JSON.parse(sessionStorage.getItem(key));return value&&typeof value==='object'&&!Array.isArray(value)?value:{}}catch{return {}}}
  let state=read();
  function save(){
    state.sections=Object.fromEntries([...sidebar.querySelectorAll('.sidebar-section')].map(node=>[sectionKey(node),node.open]));
    if(innerWidth>900)state.desktop=desktop.scrollTop;
    else if(sidebar.classList.contains('mobile-open'))state.mobile=mobile.scrollTop;
    try{sessionStorage.setItem(key,JSON.stringify(state))}catch{}
  }
  function setMobileSidebar(open){
    sidebar.classList.toggle('mobile-open',open);toggle.setAttribute('aria-expanded',String(open));toggle.textContent=open?'关闭':'菜单';
    if(open)sidebar.restoreNavigation();
  }
  sidebar.setMobileOpen=setMobileSidebar;
  sidebar.addEventListener('toggle',event=>{if(event.target.matches?.('.sidebar-section'))save()},true);
  desktop.addEventListener('scroll',()=>{if(innerWidth>900)save()},{passive:true});
  mobile.addEventListener('scroll',()=>{if(innerWidth<=900)save()},{passive:true});
  sidebar.addEventListener('click',event=>{if(event.target.closest('a'))save()});
  window.addEventListener('pagehide',save);
  window.addEventListener('pageshow',()=>{state=read();sidebar.restoreNavigation()});
  toggle.addEventListener('click',event=>{event.stopPropagation();setMobileSidebar(!sidebar.classList.contains('mobile-open'))});
  document.addEventListener('click',event=>{if(innerWidth<=900&&!sidebar.contains(event.target)){save();setMobileSidebar(false)}});
  // An open project context menu takes Escape first.
  document.addEventListener('keydown',event=>{const menu=document.getElementById('sidebarProjectMenu');if(event.key==='Escape'&&(!menu||menu.hidden)){save();setMobileSidebar(false)}});
  window.addEventListener('resize',()=>{if(innerWidth>900)setMobileSidebar(false);sidebar.restoreNavigation()});
})();
