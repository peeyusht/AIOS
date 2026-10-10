/* Search page, injected into the built bundle (same scope as the other pages).
   Uses the bundle's helpers: f, Z, uc, al, Ba, Yn, Gf, He, cc, Wl, cm, Qt, Ya, Cf, g1 (search icon), d1 (refresh icon). */
const SFsearchIcon=Qt("file-search",[["path",{d:"M14 2v4a2 2 0 0 0 2 2h4",key:"s1"}],["path",{d:"M4.268 21a2 2 0 0 0 1.727 1H18a2 2 0 0 0 2-2V7l-5-5H6a2 2 0 0 0-2 2v3",key:"s2"}],["path",{d:"m9 18-1.5-1.5",key:"s3"}],["circle",{cx:"5",cy:"14",r:"3",key:"s4"}]]);
const SFstatusText={ok:"Text indexed",name_only:"Name only",no_text:"No text (scanned?)",cloud:"Cloud-only, name only",error:"Error"};
function SFhl(text,q){
  const words=(q.toLowerCase().match(/[\w\-./]+/g)||[]).filter(w=>w.length>1);
  if(!words.length||!text)return text;
  const rx=new RegExp("("+words.map(w=>w.replace(/[.*+?^${}()|[\]\\]/g,"\\$&")).join("|")+")","ig");
  return text.split(rx).map((part,i)=>i%2?f.jsx("mark",{style:{background:"var(--warning-soft, #fdf2c4)",color:"inherit",padding:"0 1px",borderRadius:"2px"},children:part},i):part);
}
function SFsearch(){
  const[q,setQ]=Z.useState(()=>{try{return sessionStorage.getItem("sf-q")??""}catch{return""}});
  const[scope,setScope]=Z.useState("all"),[types,setTypes]=Z.useState("any");
  const[res,setRes]=Z.useState(null),[loading,setLoading]=Z.useState(!1),[err,setErr]=Z.useState(null),[msg,setMsg]=Z.useState(null);
  const dq=X1(q,350);
  const{data:st,reload}=Ya(()=>Wl("/api/search/status"),5e3,[]);
  Z.useEffect(()=>{try{sessionStorage.setItem("sf-q",q)}catch{}},[q]);
  Z.useEffect(()=>{if(!dq.trim()){setRes(null);return}let live=!0;setLoading(!0);setErr(null);
    Wl(`/api/search?q=${encodeURIComponent(dq)}&scope=${scope}&types=${types}`).then(r=>{live&&setRes(r)}).catch(e=>{live&&setErr(e instanceof Error?e.message:String(e))}).finally(()=>{live&&setLoading(!1)});
    return()=>{live=!1}},[dq,scope,types]);
  const act=async(url,path)=>{setMsg(null);try{const r=await cm(url,{path});if(r&&r.ok===!1)setMsg(r.message)}catch(e){setMsg(e instanceof Error?e.message:String(e))}};
  const rebuild=async()=>{setMsg(null);const r=await cm("/api/search/rebuild",{});setMsg(r.message);reload()};
  const indexing=st&&st.running&&st.phase!=="idle";
  const tabs=(val,set,opts,label)=>f.jsx("div",{role:"tablist","aria-label":label,className:"flex flex-wrap rounded-md border bg-card p-0.5",children:opts.map(([k,l])=>f.jsx("button",{role:"tab","aria-selected":val===k,onClick:()=>set(k),className:`rounded-sm px-2.5 py-1 text-sm ${val===k?"bg-accent font-medium":"text-muted-foreground hover:text-foreground"}`,children:l},k))});
  return SFx("div",{className:"space-y-4"},
    SFx("div",{className:"flex flex-wrap items-center gap-3"},
      SFx("h1",{className:"text-lg font-semibold"},"Search"),
      SFx("span",{className:"text-xs text-muted-foreground","aria-live":"polite"},
        !st?"Loading…":st.disabled?"Search is off in config.yaml":indexing?`Indexing ${st.done??0} of ${st.todo??0}${st.current?` · ${st.current}`:""}`:`${(st.files??0).toLocaleString()} files indexed · ${(st.chunks??0).toLocaleString()} passages`)),
    SFx("label",{className:"relative block"},SFx("span",{className:"sr-only"},"Search your files"),
      f.jsx(g1,{className:"pointer-events-none absolute top-1/2 -translate-y-1/2 text-muted-foreground",style:{left:"12px",width:"18px",height:"18px"}}),
      f.jsx("input",{autoFocus:!0,value:q,onChange:e=>setQ(e.target.value),placeholder:"Describe what you're looking for, e.g. \"posture audit findings for the bank\" or \"PVK-2026-TCS-001\"",className:"w-full rounded-md border bg-card",style:{padding:"10px 12px 10px 40px",fontSize:"15px"}})),
    SFx("div",{className:"flex flex-wrap items-center gap-3"},
      tabs(scope,setScope,[["all","Everywhere"],["para","Organized (PARA)"],["inbox","Downloads"]],"Where"),
      tabs(types,setTypes,[["any","Any type"],["docs","Documents"],["pdf","PDF"],["sheets","Sheets"],["slides","Slides"]],"Type"),
      res&&!loading&&SFx("span",{className:"text-xs text-muted-foreground"},`${res.results.length} result${res.results.length===1?"":"s"} · ${res.ms} ms`,res.semantic?"":" · keyword only"),
      loading&&SFx("span",{className:"text-xs text-muted-foreground"},"Searching…")),
    err&&f.jsx(Yn,{error:err}),
    msg&&SFx("div",{role:"alert",className:"rounded-md border border-warning bg-warning-soft px-3 py-2 text-sm text-warning"},msg),
    res&&!res.semantic&&res.semantic_error&&SFx("div",{className:"rounded-md border border-warning bg-warning-soft px-3 py-2 text-sm text-warning"},"Meaning-based search is unavailable right now, so these are keyword matches only: ",res.semantic_error),
    !q.trim()&&st&&!st.disabled&&(st.files??0)===0&&f.jsx(Gf,{title:indexing?"Building the index…":"Index is empty",children:indexing?"The first pass reads every document once. Results appear as soon as files are indexed; recent documents go first.":"It starts automatically when the agent runs."}),
    res&&res.results.length===0&&!loading&&f.jsx(Gf,{title:"No matches",children:"Try other words, or widen the filters."}),
    res&&res.results.length>0&&SFx("ol",{className:"space-y-2"},res.results.map((r,i)=>SFx("li",{key:r.path,className:"panel px-4 py-3"},
      SFx("div",{className:"flex flex-wrap items-start gap-x-3 gap-y-1"},
        SFx("div",{className:"min-w-0 flex-1"},
          SFx("div",{className:"truncate font-medium",title:r.path},SFhl(r.name,dq)),
          SFx("div",{className:"truncate text-xs text-muted-foreground",title:r.path},r.folder," · ",He(r.size)," · modified ",cc(r.modified),r.part?` · part ${r.part}`:"")),
        SFx("div",{className:"flex shrink-0 items-center gap-1"},
          r.keyword&&f.jsx(Ba,{tone:"info",children:"words"}),
          r.similarity!=null&&f.jsx(Ba,{tone:r.similarity>=.6?"success":r.similarity>=.5?"muted":"muted",children:`meaning ${Math.round(r.similarity*100)}%`}),
          r.status!=="ok"&&f.jsx(Ba,{tone:"muted",children:SFstatusText[r.status]??r.status}),
          r.openable&&f.jsx("button",{onClick:()=>act("/api/search/open",r.path),className:"rounded-md border bg-card px-2 py-1 text-xs hover:bg-accent",children:"Open"}),
          f.jsx("button",{onClick:()=>act("/api/search/reveal",r.path),title:"Open Explorer with this file selected",className:"rounded-md border bg-card px-2 py-1 text-xs hover:bg-accent",children:"Show"}))),
      r.snippet&&SFx("p",{className:"mt-2 text-sm text-muted-foreground",style:{overflowWrap:"anywhere"}},SFhl(r.snippet,dq))))),
    st&&!st.disabled&&f.jsx(al,{title:"Index",actions:SFx(uc,{onClick:rebuild,disabled:indexing},"Rebuild index"),children:f.jsx(Cf,{rows:[
      ["Status",indexing?SFx("span",{className:"flex items-center gap-2"},f.jsx(d1,{className:"h-4 w-4 animate-spin"}),`${st.phase} · ${st.done??0} of ${st.todo??0}`,st.current?` · ${st.current}`:""):st.last_sweep?`Up to date · last checked ${cc(st.last_sweep)}`:"Starting"],
      ["Folders",SFx("div",{className:"space-y-0.5"},(st.roots??[]).map(r=>SFx("div",{key:r.path,className:"font-mono text-xs"},r.path,r.exists?"":" (not found)")))],
      ["Files",Object.entries(st.by_status??{}).map(([k,v])=>`${SFstatusText[k]??k}: ${v.toLocaleString()}`).join(" · ")||"–"],
      ["Model",SFx("span",null,f.jsx("span",{className:"font-mono text-xs",children:st.model}),st.model_ok===!1?" (not installed)":"")],
      ["Keyword index",st.fts?"SQLite FTS5":"basic (FTS5 not available)"],
      ["Index size",He(st.db_bytes)],
      ["Privacy","Runs only on this PC. search.db holds text from your documents; delete it any time and it is rebuilt."],
      ...(st.last_error?[["Last problem",SFx("span",{className:"text-warning"},st.last_error)]]:[]),
      ...((st.errors??[]).length?[["Files that failed",SFx("div",{className:"space-y-0.5 text-xs"},st.errors.slice(0,8).map(e=>SFx("div",{key:e.path,className:"truncate",title:e.path+": "+e.error},e.path.split(/[\\/]/).pop()," — ",e.error)))]]:[])]})}));
}
