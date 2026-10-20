/* Shared page helpers: one top-right toast, clipboard copy with a fallback for
   browsers that refuse the async clipboard, and file preview rendering. Page
   scripts use window.EmberUI and window.EmberPreview instead of their own copies. */
(function(){
  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.setAttribute('aria-atomic', 'true');
  document.body.appendChild(toast);
  let timer = null;
  function showToast(msg, type='info', duration=3000){
    toast.textContent = msg;
    toast.className = 'toast ' + type + ' show';
    toast.setAttribute('role', type === 'error' ? 'alert' : 'status');
    toast.setAttribute('aria-live', type === 'error' ? 'assertive' : 'polite');
    clearTimeout(timer);
    timer = setTimeout(()=>toast.classList.remove('show'), duration);
  }
  async function copyPrompt(text){
    try{
      await navigator.clipboard.writeText(text);
      return true;
    }catch(error){
      const fallback = document.createElement('textarea');
      fallback.value = text;
      fallback.setAttribute('readonly', '');
      fallback.style.position = 'fixed';
      fallback.style.opacity = '0';
      document.body.appendChild(fallback);
      fallback.select();
      let copied = false;
      try{ copied = document.execCommand('copy'); }catch(copyError){}
      fallback.remove();
      return copied;
    }
  }
  const previewEsc = value=>String(value??'').replace(/[&<>\"]/g, char=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[char]));
  /* Fixed-size HTML (posters, slides) renders at its intrinsic size and is scaled to fit the pane.
     The sandboxed frame is never read: the size comes from a WxH filename or the page's own CSS text. */
  function htmlNameSize(name){
    const match=/(\d{2,5})\s*[x×X]\s*(\d{2,5})/.exec(String(name||''));
    return match?{width:Number(match[1]),height:Number(match[2])}:null;
  }
  function htmlTextSize(text){
    const source=String(text||'').slice(0,200000),size={};
    const rule=/(?:^|[\s,;}>])(?:html|body)\s*\{([^}]*)\}/gi;let match;
    while((match=rule.exec(source))){
      const width=/(?:^|[\s;])width\s*:\s*(\d+(?:\.\d+)?)px/i.exec(match[1]),height=/(?:^|[\s;])height\s*:\s*(\d+(?:\.\d+)?)px/i.exec(match[1]);
      if(width&&!size.width)size.width=Number(width[1]);if(height&&!size.height)size.height=Number(height[1]);
    }
    if(!(size.width&&size.height)){
      const meta=/<meta[^>]+name=["']?viewport["']?[^>]*content=["']([^"']*)["']/i.exec(source)||/<meta[^>]+content=["']([^"']*)["'][^>]*name=["']?viewport/i.exec(source);
      if(meta){const width=/width\s*=\s*(\d+)/i.exec(meta[1]),height=/height\s*=\s*(\d+)/i.exec(meta[1]);if(width&&height){size.width=Number(width[1]);size.height=Number(height[1])}}
    }
    return size.width>0&&size.height>0?size:null;
  }
  function bindHtmlFit(container){
    container.querySelectorAll('.html-preview[data-html-fit]').forEach(view=>{
      if(view.dataset.fitBound==='1')return;view.dataset.fitBound='1';
      const stage=view.querySelector('.html-preview-stage'),frame=stage&&stage.querySelector('iframe');
      if(!frame)return;
      const apply=(width,height)=>{
        if(!(width>0&&height>0))return;
        view.dataset.fitWidth=String(width);view.dataset.fitHeight=String(height);
        stage.classList.add('fitted');frame.style.width=`${width}px`;frame.style.height=`${height}px`;
        const fit=()=>{
          const availableWidth=stage.clientWidth,availableHeight=stage.clientHeight;
          if(!availableWidth||!availableHeight)return;
          const scale=Math.min(availableWidth/width,availableHeight/height,1),left=(availableWidth-width*scale)/2,top=(availableHeight-height*scale)/2;
          frame.style.transform=`translate(${left}px, ${top}px) scale(${scale})`;view.dataset.fitScale=scale.toFixed(4);
        };
        fit();if(window.ResizeObserver)new ResizeObserver(fit).observe(stage);else window.addEventListener('resize',fit);
      };
      const width=Number(view.dataset.fitWidth),height=Number(view.dataset.fitHeight);
      if(width&&height){apply(width,height);return}
      const url=view.dataset.contentUrl;if(!url||!window.fetch)return;
      fetch(url,{credentials:'same-origin'}).then(response=>response.ok?response.text():'').then(text=>{const size=htmlTextSize(text);if(size&&view.isConnected)apply(size.width,size.height)}).catch(()=>{});
    });
  }
  function previewHtml(data){
    const previewKind=String(data.preview_kind||data.kind||'');
    if(data.kind==='markdown'||data.kind==='text'){
      return `<article class="article md">${data.body_html||'<p>文件过大或暂时无法读取。</p>'}</article>`;
    }
    if(data.kind==='image') return `<div class="library-preview-media"><img src="${previewEsc(data.raw_url)}" alt="${previewEsc(data.name)}"></div>`;
    if(data.kind==='video') return `<div class="library-preview-media"><video src="${previewEsc(data.raw_url)}" controls preload="metadata"></video></div>`;
    if(data.kind==='audio') return `<div class="library-preview-media"><audio src="${previewEsc(data.raw_url)}" controls preload="metadata"></audio></div>`;
    if(previewKind==='document'){
      if(data.preview_error||!data.page_count){
        return `<div class="document-preview-error"><strong>${previewEsc(data.document_label||'文档')} 暂时无法预览</strong><span>${previewEsc(data.preview_error||'文件没有可显示的页面。')} 你仍可以在 Finder 中显示或用系统应用打开。</span></div>`;
      }
      return `<div class="document-preview" data-document-preview data-page-count="${Number(data.page_count)||1}" data-page-url="${previewEsc(data.page_url)}"><div class="document-toolbar"><div class="document-toolbar-group"><button type="button" data-document-prev aria-label="上一页">‹</button><span class="document-page-counter"><strong data-document-current>1</strong> / ${Number(data.page_count)||1}</span><button type="button" data-document-next aria-label="下一页">›</button></div><span class="document-kind">${previewEsc(data.document_label||'文档')}</span><div class="document-toolbar-group"><button type="button" data-document-zoom-out aria-label="缩小">−</button><span class="document-zoom-label" data-document-zoom-label>适合页面</span><button type="button" data-document-zoom-in aria-label="放大">＋</button><button type="button" data-document-fit>适页</button></div></div><div class="document-canvas" tabindex="0"><div class="document-page-wrap"><img class="document-page loading" data-document-page src="${previewEsc(data.page_url)}1" alt="${previewEsc(data.name)} 第 1 页"></div></div></div>`;
    }
    if(previewKind==='html'){
      const fitSize=htmlNameSize(data.name);
      const fitAttrs=fitSize?` data-fit-width="${fitSize.width}" data-fit-height="${fitSize.height}"`:'';
      return `<div class="html-preview" data-html-fit data-content-url="${previewEsc(data.content_url)}"${fitAttrs}><div class="html-preview-stage"><iframe src="${previewEsc(data.content_url)}" title="${previewEsc(data.name)}" sandbox="" referrerpolicy="no-referrer"></iframe></div><div class="html-preview-note">${previewEsc(data.preview_note||'HTML 以隔离模式显示。')}</div></div>`;
    }
    if(previewKind==='office'||data.kind==='pdf'){
      return `<div class="library-preview-media"><iframe src="${previewEsc(data.raw_url)}" title="${previewEsc(data.name)}"></iframe></div>`;
    }
    return `<div class="library-file-info"><h3>${previewEsc(data.name)}</h3><div class="library-file-meta"><span>类型</span><span>${previewEsc(data.mime)}</span><span>大小</span><span>${Math.max(1,Math.round((Number(data.size)||0)/1024)).toLocaleString()} KB</span><span>更新时间</span><span>${previewEsc(data.updated_at||'')}</span><span>路径</span><span>${previewEsc(data.relative_path)}</span></div></div>`;
  }
  function bindPreview(container){
    bindHtmlFit(container);
    const viewer=container.querySelector('[data-document-preview]');
    if(!viewer||viewer.dataset.bound==='1') return;
    viewer.dataset.bound='1';
    const total=Math.max(1,Number(viewer.dataset.pageCount)||1),base=viewer.dataset.pageUrl,img=viewer.querySelector('[data-document-page]'),canvas=viewer.querySelector('.document-canvas'),wrap=viewer.querySelector('.document-page-wrap'),current=viewer.querySelector('[data-document-current]'),label=viewer.querySelector('[data-document-zoom-label]'),prev=viewer.querySelector('[data-document-prev]'),next=viewer.querySelector('[data-document-next]');
    let page=1,zoom=100,fitWidth=0;
    function updatePage(nextPage){
      page=Math.max(1,Math.min(total,nextPage));
      current.textContent=String(page);prev.disabled=page===1;next.disabled=page===total;
      img.classList.add('loading');img.src=base+page;img.alt=`第 ${page} 页`;canvas.scrollTo({top:0,left:0,behavior:'smooth'});
    }
    function updateZoom(nextZoom){
      zoom=Math.max(50,Math.min(200,nextZoom));wrap.style.width=fitWidth?`${Math.round(fitWidth*zoom/100)}px`:`min(${zoom}%, ${Math.round(1120*zoom/100)}px)`;label.textContent=zoom===100?'适合页面':zoom+'%';
    }
    function fitPage(){
      if(!img.naturalWidth||!img.naturalHeight)return;const style=getComputedStyle(canvas),availableWidth=canvas.clientWidth-parseFloat(style.paddingLeft)-parseFloat(style.paddingRight),availableHeight=canvas.clientHeight-parseFloat(style.paddingTop)-parseFloat(style.paddingBottom);fitWidth=Math.max(1,Math.min(1120,availableWidth,availableHeight*img.naturalWidth/img.naturalHeight));updateZoom(zoom);
    }
    img.addEventListener('load',()=>{img.classList.remove('loading');fitPage()});
    img.addEventListener('error',()=>{img.classList.remove('loading');showToast('这一页暂时无法生成预览', 'error', 4000)});
    prev.addEventListener('click',()=>updatePage(page-1));next.addEventListener('click',()=>updatePage(page+1));viewer.querySelector('[data-document-zoom-out]').addEventListener('click',()=>updateZoom(zoom-25));viewer.querySelector('[data-document-zoom-in]').addEventListener('click',()=>updateZoom(zoom+25));viewer.querySelector('[data-document-fit]').addEventListener('click',()=>updateZoom(100));canvas.addEventListener('keydown',event=>{if(event.key==='ArrowLeft'){event.preventDefault();updatePage(page-1)}else if(event.key==='ArrowRight'){event.preventDefault();updatePage(page+1)}});new ResizeObserver(fitPage).observe(canvas);updatePage(1);updateZoom(100);
  }
  window.EmberUI={toast:showToast,copyPrompt};
  window.EmberPreview={html:previewHtml,bind:bindPreview};
})();
