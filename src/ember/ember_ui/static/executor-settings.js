/* 执行环境 editor on the settings page: edit, add, find and remove local programs, choose the default,
   check the paths and save. Everything is a draft until saved. The page renders the markup
   (ember_ui/pages/settings.py execution()); mount(root, options) wires it and returns {destroy}.
   Options (each optional; the defaults are the full workbench's form posts):
     discover() -> Promise<{candidates, warnings, limited}>
     check({executors, default_executor}) -> Promise<{notice}>
     save({executors, default_executor}) -> Promise   omitted: the form submits as usual */
(()=>{
const postForm=(path,body,signal,fallback)=>fetch(path,{method:'POST',body,headers:{Accept:'application/json'},signal}).then(response=>response.json().then(data=>{
  if(response.status===403&&typeof data.csrf_token==='string')document.querySelectorAll('input[name="csrf"]').forEach(input=>input.value=data.csrf_token);
  if(!response.ok||!data.ok)throw new Error(data.error||fallback);return data}));
function mount(root=document,options={}){
  const $=id=>root.querySelector('#'+id);
  const form=$('executorSettingsForm'),button=$('executorDiscoverSoftware'),panel=$('executorDiscovery'),closePanel=$('executorDiscoveryClose'),defaultField=$('executorDefaultField'),status=$('executorDiscoveryStatus'),list=$('executorDiscoveryCandidates'),registered=$('executorLocalList'),addButton=$('executorAddSoftware');
  if(!form||!button||!panel||!status||!list)return null;
  const selected=form.elements.default_executor,serialized=form.elements.executors,checkButton=form.querySelector('[data-executor-check]');
  let entries=JSON.parse(serialized.value);
  const editor=$('executorSettingsEditor'),edit=$('executorSettingsEdit'),cancel=$('executorSettingsCancel'),state=$('executorSettingsState'),summary=$('executorCurrentEnvironment'),manualName=$('executorSoftwareName'),manualKind=$('executorSoftwareKind'),manualPath=$('executorSoftwarePath');
  const savedEntries=JSON.parse(serialized.value),savedDefault=selected.value,savedReady=summary.dataset.environmentState==='saved',initialState=state.textContent;
  const discover=options.discover||(signal=>postForm('/actions/discover-executor-software',new URLSearchParams({csrf:form.elements.csrf.value}),signal,'查找暂时失败，请重试或手动填写路径。'));
  const check=options.check||((draft,signal,submitter)=>postForm(new URL(submitter.getAttribute('formaction')||form.action,location.href).pathname,new URLSearchParams(new FormData(form)),signal,'路径检查失败，请核对后重试。'));
  let checkEpoch=0,checkRequest=null,discoveryEpoch=0,discoveryRequest=null,saving=false;
  const draft=()=>({executors:entries.map(entry=>({...entry})),default_executor:selected.value});
  const signature=()=>JSON.stringify({executors:entries,default_executor:selected.value});
  const savedSignature=signature();
  const feedback=(text,kind='unchanged')=>{state.textContent=text;state.dataset.state=kind;};
  const changed=()=>{checkEpoch++;if(manualName.value.trim()||manualPath.value.trim()){feedback('新软件尚未加入清单，请先点击「手工添加」。','dirty');}else if(signature()!==savedSignature){feedback('已修改，尚未保存。当前生效的环境没有改变；请检查后保存。','dirty');}else{feedback(initialState);}};
  const message=(text,kind='dirty')=>feedback(text,kind);
  const collapse=()=>{discoveryEpoch++;discoveryRequest?.abort();panel.hidden=true;list.replaceChildren();button.setAttribute('aria-expanded','false');};
  const highlight=()=>{defaultField.classList.remove('needs-choice');defaultField.classList.add('is-chosen');setTimeout(()=>defaultField.classList.remove('is-chosen'),1600);};
  const choose=id=>{selected.value=id;changed();highlight();};
  const sync=()=>{const previous=selected.value;selected.replaceChildren();const empty=document.createElement('option');empty.value='';empty.textContent='请选择本机软件';selected.append(empty);for(const entry of entries){const option=document.createElement('option');option.value=entry.id;option.textContent=entry.label;selected.append(option);}selected.value=entries.some(entry=>entry.id===previous)?previous:'';serialized.value=JSON.stringify(entries);};
  const render=()=>{registered.replaceChildren();if(!entries.length){const empty=document.createElement('p');empty.className='executor-local-empty';empty.textContent='还没有登记本机软件。可以自动查找，或在下面手工添加。';registered.append(empty);}for(const entry of entries){const row=document.createElement('div');row.className='executor-local-row';row.dataset.executorRow=entry.id;const name=document.createElement('input'),kind=document.createElement('select'),path=document.createElement('input'),remove=document.createElement('button');name.value=entry.label;name.maxLength=80;name.setAttribute('aria-label','软件名称');name.dataset.executorName='';path.value=entry.path;path.maxLength=4096;path.spellcheck=false;path.setAttribute('aria-label','软件路径');path.dataset.executorPath='';for(const [value,label] of [['app','桌面应用'],['command','命令行程序']]){const option=document.createElement('option');option.value=value;option.textContent=label;kind.append(option);}kind.value=entry.kind;kind.setAttribute('aria-label','软件类型');kind.dataset.executorKind='';name.addEventListener('input',()=>{entry.label=name.value;sync();changed();});path.addEventListener('input',()=>{entry.path=path.value;sync();changed();});kind.addEventListener('change',()=>{entry.kind=kind.value;sync();changed();});remove.type='button';remove.className='button ghost';remove.textContent='移除';remove.setAttribute('aria-label','移除 '+entry.label);remove.addEventListener('click',()=>{entries=entries.filter(item=>item.id!==entry.id);sync();render();changed();message('已从当前表单移除；尚未保存。');addButton.focus();});row.append(name,kind,path,remove);registered.append(row);}};
  const add=entry=>{const existing=entries.find(item=>item.kind===entry.kind&&item.path===entry.path);if(!existing){if(entries.length>=32){message('最多登记 32 项本机软件，请先移除不需要的项目。');return false;}entries.push(entry);sync();render();changed();}const id=existing?.id||entry.id;if(!selected.value&&entries.length===1){choose(id);message('已添加并设为默认软件；尚未保存，请检查后保存。');return true;}[...registered.children].find(row=>row.dataset.executorRow===id)?.querySelector('[data-executor-path]')?.focus();message('已添加到本机软件列表；尚未保存，请选择默认软件、检查后保存。');return true;};
  addButton.addEventListener('click',()=>{if(!manualName.value.trim()||!manualPath.value.trim()){message('请填写软件名称和软件路径。','error');(!manualName.value.trim()?manualName:manualPath).focus();return;}if(add({id:'local-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2,10),label:manualName.value.trim(),kind:manualKind.value,path:manualPath.value.trim()})){manualName.value='';manualPath.value='';changed();}});
  selected.addEventListener('change',()=>{defaultField.classList.remove('needs-choice');changed();});
  closePanel.addEventListener('click',()=>{collapse();button.focus();});
  panel.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();collapse();button.focus();}});manualName.addEventListener('input',changed);manualPath.addEventListener('input',changed);manualKind.addEventListener('change',changed);
  edit.addEventListener('click',()=>{editor.hidden=false;edit.setAttribute('aria-expanded','true');(registered.querySelector('[data-executor-name]')||selected).focus();});
  cancel.addEventListener('click',()=>{checkEpoch++;checkRequest?.abort();discoveryEpoch++;discoveryRequest?.abort();entries=JSON.parse(JSON.stringify(savedEntries));sync();selected.value=savedDefault;manualName.value='';manualPath.value='';manualKind.value='app';render();collapse();defaultField.classList.remove('needs-choice');feedback(initialState);editor.hidden=savedReady;edit.setAttribute('aria-expanded',savedReady?'false':'true');(savedReady?edit:selected).focus();});
  const setSaving=value=>{saving=value;editor.querySelectorAll('input,select,button').forEach(node=>node.disabled=value);edit.disabled=value;};
  form.addEventListener('submit',async event=>{
    const checking=event.submitter===checkButton;
    if(saving){event.preventDefault();event.stopImmediatePropagation();return;}
    if(manualName.value.trim()||manualPath.value.trim()){event.preventDefault();event.stopImmediatePropagation();feedback('新软件尚未加入清单，请先手工添加，或清空新增软件的草稿。','dirty');manualName.focus();return;}
    if(entries.length&&!selected.value){event.preventDefault();event.stopImmediatePropagation();defaultField.classList.add('needs-choice');feedback('请先在「2 · 选择默认软件」里选一个软件，再检查或保存。','error');selected.focus();return;}
    if(!checking){
      if(!options.save)return;
      event.preventDefault();event.stopImmediatePropagation();
      setSaving(true);feedback('正在保存本机清单…','saving');
      try{await options.save(draft());}catch(error){feedback(error.message||'保存失败，请重试；当前配置没有改变。','error');}finally{if(form.isConnected)setSaving(false);}
      return;
    }
    event.preventDefault();event.stopImmediatePropagation();
    const submitter=event.submitter,controller=new AbortController(),revision=++checkEpoch,checkedSignature=signature(),originalLabel=submitter.textContent;
    checkRequest=controller;submitter.disabled=true;submitter.setAttribute('aria-busy','true');submitter.textContent='正在检查…';feedback('正在检查软件路径；不会保存或启动软件。','checking');
    const timer=setTimeout(()=>controller.abort(),10000);
    try{const data=await check(draft(),controller.signal,submitter);if(revision!==checkEpoch||checkedSignature!==signature())return;feedback('路径检查通过，尚未保存。点击「保存配置」才会生效；登录和模型仍在软件内管理。','checked');window.EmberUI?.toast(data?.notice||'路径检查通过；没有保存配置。');}
    catch(error){if(revision===checkEpoch){feedback(error.name==='AbortError'?'路径检查超时，请重试；当前配置没有改变。':error.message||'路径检查失败，请重试；当前配置没有改变。','error');}}
    finally{clearTimeout(timer);if(checkRequest===controller)checkRequest=null;submitter.disabled=false;submitter.removeAttribute('aria-busy');submitter.textContent=originalLabel;}
  },true);
  render();
  button.addEventListener('click',async()=>{
    const controller=new AbortController(),revision=++discoveryEpoch,timer=setTimeout(()=>controller.abort(),10000);discoveryRequest=controller;
    button.disabled=true;button.setAttribute('aria-busy','true');button.setAttribute('aria-expanded','true');panel.hidden=false;status.textContent='正在查找本机常见 AI 软件…';list.replaceChildren();
    try{
      const data=await discover(controller.signal);
      if(revision!==discoveryEpoch)return;
      const candidates=Array.isArray(data.candidates)?data.candidates:[],warnings=Array.isArray(data.warnings)?data.warnings:[];
      status.textContent=(candidates.length?'找到 '+candidates.length+' 个候选。点「选用」即加入清单并设为默认；尚未保存。':warnings.length||data.limited?'没有可用候选，扫描结果可能不完整。':'在常见安装位置未找到受支持的软件。可手动填写路径；未安装时需先自行安装。')+(data.limited?' 已达到扫描范围限制。':'')+(warnings.length?' '+warnings.join(' '):'');
      for(const item of candidates){
        if(!['app','command'].includes(item.kind)||typeof item.path!=='string'||typeof item.id!=='string'||typeof item.label!=='string')continue;
        const row=document.createElement('div'),description=document.createElement('div'),label=document.createElement('strong'),path=document.createElement('code'),use=document.createElement('button');
        const known=entries.find(entry=>entry.kind===item.kind&&entry.path===item.path);
        row.className='executor-discovery-candidate'+(known?' is-added':'');label.textContent=item.label+' · '+(item.source||'本机路径');path.textContent=item.path;use.type='button';use.className='button ghost';use.textContent=known?'设为默认':'选用';use.setAttribute('aria-label',(known?'设为默认 ':'选用 ')+item.label+'：'+item.path);
        use.addEventListener('click',()=>{const existing=entries.find(entry=>entry.kind===item.kind&&entry.path===item.path);if(!existing&&!add({id:item.id,label:item.label,kind:item.kind,path:item.path}))return;const id=(existing||entries.find(entry=>entry.kind===item.kind&&entry.path===item.path)).id;choose(id);collapse();message('已选用 '+item.label+' 作为默认软件；尚未保存，请检查后保存。');selected.focus();});
        description.append(label,path);row.append(description,use);list.append(row);
      }
    }catch(error){if(revision===discoveryEpoch)status.textContent=error.name==='AbortError'?'查找超时，请重试或手动填写路径。':error.message||'查找暂时失败，请重试或手动填写路径。';}
    finally{clearTimeout(timer);if(discoveryRequest===controller)discoveryRequest=null;button.disabled=false;button.removeAttribute('aria-busy');}
  });
  return {destroy(){checkEpoch++;checkRequest?.abort();discoveryEpoch++;discoveryRequest?.abort();}};
}
window.EmberExecutorSettings={mount};
if(document.getElementById('executorSettingsForm'))mount();
})();
