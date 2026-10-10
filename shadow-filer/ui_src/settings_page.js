/* Settings form, injected into the built bundle. Uses the bundle's helpers: f, Z, uc, al, Ba, Yn, Wl, cm, Ee,
   Hn (unsaved-changes flag), fy (the original YAML editor, kept as "Advanced"), SFx (from cleanup_page.js). */
const SFclone=o=>JSON.parse(JSON.stringify(o??null));
const SFinput="w-full rounded-md border bg-card px-2 py-1.5 text-sm";
function SFrow({label,help,children,warn}){
  return SFx("div",{className:"grid gap-x-6 gap-y-1 py-3 sm:grid-cols-[220px_1fr]",style:{borderTop:"1px solid var(--border, rgba(127,127,127,.18))"}},
    SFx("div",null,SFx("div",{className:"text-sm font-medium"},label),help&&SFx("div",{className:"mt-0.5 text-xs text-muted-foreground"},help)),
    SFx("div",{className:"min-w-0 space-y-1.5"},children,warn&&SFx("div",{className:"text-xs text-warning"},"⚠ ",warn)));
}
function SFnum({value,onChange,min,max,step,suffix,width}){
  return SFx("span",{className:"inline-flex items-center gap-2"},
    f.jsx("input",{type:"number",value:value??"",min,max,step:step??1,onChange:e=>onChange(e.target.value===""?"":Number(e.target.value)),className:SFinput,style:{width:width??"110px"}}),
    suffix&&SFx("span",{className:"text-sm text-muted-foreground"},suffix));
}
function SFtoggle({value,onChange,label}){
  return SFx("label",{className:"inline-flex cursor-pointer items-center gap-2 text-sm"},f.jsx("input",{type:"checkbox",checked:!!value,onChange:e=>onChange(e.target.checked)}),label);
}
function SFlines({value,onChange,placeholder,rows}){
  const[t,setT]=Z.useState((value??[]).join("\n"));
  Z.useEffect(()=>{const cur=t.split("\n").map(x=>x.trim()).filter(Boolean);if(JSON.stringify(cur)!==JSON.stringify(value??[]))setT((value??[]).join("\n"))},[JSON.stringify(value)]);
  return f.jsx("textarea",{value:t,rows:rows??4,placeholder,spellCheck:!1,onChange:e=>{setT(e.target.value);onChange(e.target.value.split("\n").map(x=>x.trim()).filter(Boolean))},className:SFinput+" font-mono",style:{fontSize:"12.5px"}});
}
function SFpicker({start,onPick,onClose}){
  const[path,setPath]=Z.useState(start||""),[data,setData]=Z.useState(null),[err,setErr]=Z.useState(null);
  Z.useEffect(()=>{let live=!0;setErr(null);Wl(`/api/fs/dirs?path=${encodeURIComponent(path)}`).then(d=>{live&&setData(d)}).catch(e=>{live&&(setErr(path?"Can't open that folder":String(e)),setData(null))});return()=>{live=!1}},[path]);
  const go=p=>setPath(p);
  return SFx("div",{className:"rounded-md border bg-card p-2"},
    SFx("div",{className:"flex flex-wrap items-center gap-2"},
      SFx(uc,{onClick:()=>go(data?.parent??""),disabled:!data||(data.path===""),title:"Up one level"},"↑ Up"),
      SFx(uc,{onClick:()=>go(""),title:"Drives and common folders"},"Drives"),
      SFx("span",{className:"min-w-0 flex-1 truncate font-mono text-xs",title:data?.path},data?.path||"This PC"),
      SFx(uc,{variant:"primary",disabled:!data?.path,onClick:()=>onPick(data.path)},"Use this folder"),
      SFx(uc,{onClick:onClose},"Cancel")),
    err&&SFx("div",{className:"mt-2 text-xs text-danger"},err),
    data?.quick?.length>0&&SFx("div",{className:"mt-2 flex flex-wrap gap-1"},data.quick.map(q=>f.jsx("button",{onClick:()=>go(q.path),className:"rounded-md border px-2 py-1 text-xs hover:bg-accent",children:q.name},q.path))),
    SFx("ul",{className:"mt-2 overflow-auto text-sm",style:{maxHeight:"240px"}},
      (data?.dirs??[]).map(d=>SFx("li",{key:d.path},f.jsx("button",{onClick:()=>go(d.path),className:"w-full truncate rounded-sm px-2 py-1 text-left hover:bg-accent",children:"📁 "+d.name}))),
      data&&data.dirs.length===0&&SFx("li",{className:"px-2 py-1 text-xs text-muted-foreground"},"No subfolders")));
}
function SFpath({value,onChange,onRemove,placeholder}){
  const[chk,setChk]=Z.useState(null),[open,setOpen]=Z.useState(!1);
  const v=X1(value,400);
  Z.useEffect(()=>{if(!v){setChk(null);return}let live=!0;Wl(`/api/fs/check?path=${encodeURIComponent(v)}`).then(c=>{live&&setChk(c)}).catch(()=>{});return()=>{live=!1}},[v]);
  return SFx("div",{className:"space-y-1"},
    SFx("div",{className:"flex gap-2"},
      f.jsx("input",{value:value??"",onChange:e=>onChange(e.target.value),placeholder,spellCheck:!1,className:SFinput+" font-mono",style:{fontSize:"12.5px"}}),
      SFx(uc,{onClick:()=>setOpen(!open)},"Browse…"),
      onRemove&&SFx(uc,{onClick:onRemove,title:"Remove"},"✕")),
    chk&&SFx("div",{className:`text-xs ${chk.exists?"text-success":"text-danger"}`},chk.exists?"✓ Found":"✕ Not found",chk.expanded!==chk.input?SFx("span",{className:"text-muted-foreground"}," → ",f.jsx("span",{className:"font-mono",children:chk.expanded})):null),
    open&&f.jsx(SFpicker,{start:chk?.exists?chk.expanded:"",onClose:()=>setOpen(!1),onPick:p=>{onChange(p);setOpen(!1)}}));
}
function SFpaths({value,onChange,addLabel}){
  const list=value??[];
  return SFx("div",{className:"space-y-2"},
    list.map((p,i)=>f.jsx(SFpath,{value:p,onChange:v=>{const n=[...list];n[i]=v;onChange(n)},onRemove:()=>onChange(list.filter((_,k)=>k!==i))},i)),
    SFx(uc,{onClick:()=>onChange([...list,""])},"+ ",addLabel??"Add folder"));
}
function SFmodel({value,onChange,models,embed}){
  const list=(models??[]).filter(m=>embed?/embed|bge|minilm|e5|gte/i.test(m):!/embed|bge|minilm/i.test(m));
  const has=list.some(m=>m===value||m===value+":latest");
  return SFx("div",{className:"flex flex-wrap items-center gap-2"},
    SFx("select",{value:has?(list.includes(value)?value:value+":latest"):"__cur",onChange:e=>onChange(e.target.value),className:SFinput,style:{width:"auto",minWidth:"240px"}},
      !has&&f.jsx("option",{value:"__cur",children:`${value||"(none)"} — not installed`}),
      list.map(m=>f.jsx("option",{value:m,children:m},m))),
    !has&&SFx("span",{className:"text-xs text-warning"},"Install it with: ",f.jsx("code",{children:`ollama pull ${value}`})));
}
function SFrules({rules,onChange,dests}){
  const list=rules??[];
  const upd=(i,k,v)=>{const n=SFclone(list);n[i][k]=v;onChange(n)};
  const mv=(i,d)=>{const n=SFclone(list);const[x]=n.splice(i,1);n.splice(i+d,0,x);onChange(n)};
  const rxErr=r=>{if(!r)return null;try{new RegExp(r.replace(/\(\?P</g,"(?<"),"i");return null}catch(e){return"Not a valid pattern"}};
  return SFx("div",{className:"space-y-2"},
    list.length===0&&SFx("p",{className:"text-sm text-muted-foreground"},"No rules: every file goes to the model."),
    list.map((r,i)=>{const exts=Array.isArray(r.extensions)?r.extensions.join(", "):(r.extensions??"");const missing=r.destination&&dests&&!dests.includes(r.destination);const re=rxErr(r.name_regex);
      return SFx("div",{key:i,className:"rounded-md border p-3"},
        SFx("div",{className:"flex flex-wrap items-center gap-2"},
          SFx("span",{className:"text-xs text-muted-foreground"},`#${i+1}`),
          f.jsx("input",{value:r.name??"",onChange:e=>upd(i,"name",e.target.value),placeholder:"Rule name",className:SFinput,style:{width:"200px"}}),
          SFx("span",{className:"ml-auto flex gap-1"},
            SFx(uc,{onClick:()=>mv(i,-1),disabled:i===0,title:"Move up (rules are checked top-down)"},"↑"),
            SFx(uc,{onClick:()=>mv(i,1),disabled:i===list.length-1,title:"Move down"},"↓"),
            SFx(uc,{variant:"danger",onClick:()=>onChange(list.filter((_,k)=>k!==i)),title:"Delete rule"},"Delete"))),
        SFx("div",{className:"mt-2 grid gap-2 md:grid-cols-3"},
          SFx("label",{className:"text-xs text-muted-foreground"},"File extensions",f.jsx("input",{value:exts,onChange:e=>upd(i,"extensions",e.target.value),placeholder:".exe, .msi",spellCheck:!1,className:SFinput+" mt-1 font-mono"})),
          SFx("label",{className:"text-xs text-muted-foreground"},"and/or name contains (regex)",f.jsx("input",{value:r.name_regex??"",onChange:e=>upd(i,"name_regex",e.target.value),placeholder:"invoice|inv-\\d+",spellCheck:!1,className:SFinput+" mt-1 font-mono"}),re&&SFx("span",{className:"text-danger"},re)),
          SFx("label",{className:"text-xs text-muted-foreground"},"File into",
            SFx("select",{value:r.destination??"",onChange:e=>upd(i,"destination",e.target.value),className:SFinput+" mt-1"},
              f.jsx("option",{value:"",children:"Choose a folder…"}),
              missing&&f.jsx("option",{value:r.destination,children:`${r.destination} (not found)`}),
              (dests??[]).map(d=>f.jsx("option",{value:d,children:d},d))),
            missing&&SFx("span",{className:"text-warning"},"⚠ This folder doesn't exist in your PARA tree, so these predictions can never match."))));}),
    SFx(uc,{onClick:()=>onChange([...list,{name:`rule-${list.length+1}`,extensions:[],name_regex:"",destination:""}])},"+ Add rule"));
}
function SFocrTest(){
  const[r,setR]=Z.useState(null),[busy,setBusy]=Z.useState(!1);
  const run=async()=>{setBusy(!0);setR(null);try{setR(await cm("/api/ocr/selftest",{}))}catch(e){setR({ok:!1,message:String(e?.message??e)})}setBusy(!1)};
  return SFx("div",{className:"space-y-1.5"},SFx(uc,{onClick:run,disabled:busy},busy?"Testing…":"Test OCR"),
    r&&SFx("div",{className:`text-sm ${r.ok?"text-success":"text-danger"}`},r.message),
    r&&!r.ok&&(r.image||r.pdf)&&SFx("div",{className:"font-mono text-xs text-muted-foreground"},"image: ",r.image?.text||r.image?.error||"(nothing)"," · pdf: ",r.pdf?.text||r.pdf?.error||"(nothing)"));
}
function SFsettings(){
  const[mode,setMode]=Z.useState("form");
  const[meta,setMeta]=Z.useState(null),[orig,setOrig]=Z.useState(null),[form,setForm]=Z.useState(null),[err,setErr]=Z.useState(null);
  const[saving,setSaving]=Z.useState(!1),[res,setRes]=Z.useState(null),[restarting,setRestarting]=Z.useState(null);
  const load=()=>Wl("/api/settings").then(d=>{setMeta(d);setOrig(SFclone(d.raw));setForm(SFclone(d.raw));setErr(null)}).catch(e=>setErr(String(e?.message??e)));
  Z.useEffect(()=>{load()},[]);
  const dirty=form&&orig&&JSON.stringify(form)!==JSON.stringify(orig);
  Z.useEffect(()=>{Hn.dirty=!!dirty;const h=e=>{dirty&&(e.preventDefault(),e.returnValue="")};window.addEventListener("beforeunload",h);return()=>window.removeEventListener("beforeunload",h)},[dirty]);
  Z.useEffect(()=>()=>{Hn.dirty=!1},[]);
  const set=(path,v)=>setForm(old=>{const n=SFclone(old);const ks=path.split(".");let o=n;for(const k of ks.slice(0,-1)){if(typeof o[k]!=="object"||o[k]===null)o[k]={};o=o[k]}o[ks[ks.length-1]]=v;return n});
  const get=(path,dflt)=>{let o=form;for(const k of path.split(".")){if(o==null)return dflt;o=o[k]}return o??dflt};
  const dc=k=>meta?.defaults?.cleanup?.[k], ds=k=>meta?.defaults?.search?.[k], dO=k=>meta?.defaults?.ocr?.[k], dA=k=>meta?.defaults?.autofile?.[k];
  const save=async()=>{setSaving(!0);setRes(null);try{const r=await cm("/api/settings",{raw:form});setRes(r);if(r.ok){await load()}}catch(e){setRes({ok:!1,message:e instanceof Error?e.message:String(e)})}setSaving(!1)};
  const restart=async()=>{setRestarting("Restarting…");try{const r=await Ee.restart();if(!r.ok){setRestarting(r.message);return}Hn.dirty=!1;await new Promise(s=>setTimeout(s,1500));for(;;){try{await Ee.status();window.location.reload();return}catch{await new Promise(s=>setTimeout(s,1500))}}}catch(e){setRestarting(String(e?.message??e))}};
  const switchMode=m=>{if(m!=="form"&&dirty&&!window.confirm("You have unsaved changes in the form. Discard them?"))return;if(m!=="form")setForm(SFclone(orig));else load();setMode(m)};
  const dests=meta?.destinations??[];
  const searchOff=get("search.enabled",ds("enabled"))===!1;
  const header=SFx("div",{className:"flex flex-wrap items-center gap-2"},
    SFx("h1",{className:"mr-2 text-lg font-semibold"},"Settings"),
    f.jsx("div",{role:"tablist","aria-label":"Editor",className:"flex rounded-md border bg-card p-0.5",children:[["form","Settings"],["yaml","Advanced (YAML)"]].map(([k,l])=>f.jsx("button",{role:"tab","aria-selected":mode===k,onClick:()=>switchMode(k),className:`rounded-sm px-2.5 py-1 text-sm ${mode===k?"bg-accent font-medium":"text-muted-foreground hover:text-foreground"}`,children:l},k))}),
    mode==="form"&&dirty&&SFx("span",{className:"text-xs text-warning"},"● unsaved changes"),
    mode==="form"&&SFx("span",{className:"ml-auto flex gap-2"},
      SFx(uc,{onClick:()=>{setForm(SFclone(orig));setRes(null)},disabled:!dirty||saving},"Discard"),
      SFx(uc,{variant:"primary",onClick:save,disabled:!dirty||saving},saving?"Saving…":"Save")));
  if(mode==="yaml")return SFx("div",{className:"space-y-4"},header,f.jsx(fy,{}));
  if(err)return SFx("div",{className:"space-y-4"},header,f.jsx(Yn,{error:err}));
  if(!form)return SFx("div",{className:"space-y-4"},header,SFx("p",{className:"text-sm text-muted-foreground"},"Loading…"));
  const restartBox=(res?.restart_needed||meta?.restart_needed)&&SFx("div",{className:"flex flex-wrap items-center gap-3 rounded-md border border-warning bg-warning-soft px-3 py-2 text-sm text-warning"},
    "Some changes (watched folders, PARA root or UI port) take effect after the agent restarts.",
    SFx(uc,{variant:"danger",onClick:restart,disabled:!!restarting},restarting??"Restart agent now"));
  return SFx("div",{className:"space-y-4",style:{paddingBottom:"64px"}},
    header,
    res&&SFx("div",{role:"status",className:`rounded-md border px-3 py-2 text-sm ${res.ok?"border-success bg-success-soft text-success":"border-danger bg-danger-soft text-danger"}`},res.message),
    restartBox,
    f.jsx(al,{title:"Folders",children:SFx("div",{style:{marginTop:"-12px"}},
      f.jsx(SFrow,{label:"Watched folders",help:"New files here get a predicted destination. Usually Downloads. Needs a restart.",children:f.jsx(SFpaths,{value:get("inbox_folders",[]),onChange:v=>set("inbox_folders",v)})}),
      f.jsx(SFrow,{label:"PARA root",help:"Where you file things. Needs a restart.",children:f.jsx(SFpath,{value:get("para_root",""),onChange:v=>set("para_root",v)})}),
      f.jsx(SFrow,{label:"Destination depth",help:`How deep the model may choose. ${dests.length} folders at the current depth.`,warn:dests.length>80?"More than 80 folders: small models get worse with long lists.":null,
        children:SFx("select",{value:get("destination_depth",2),onChange:e=>set("destination_depth",Number(e.target.value)),className:SFinput,style:{width:"auto"}},[1,2,3,4,5].map(n=>f.jsx("option",{value:n,children:n===1?"1 — e.g. 1-Projects":n===2?"2 — e.g. 1-Projects/Client":`${n} levels`},n)))}),
      f.jsx(SFrow,{label:"Never suggest",help:"Folders the model may not choose. Click to toggle.",children:
        dests.length===0?SFx("p",{className:"text-sm text-muted-foreground"},"PARA root not found."):
        SFx("div",{className:"flex flex-wrap gap-1"},dests.map(d=>{const on=(get("exclude_destinations",[])||[]).includes(d);return f.jsx("button",{onClick:()=>{const cur=get("exclude_destinations",[])||[];set("exclude_destinations",on?cur.filter(x=>x!==d):[...cur,d])},"aria-pressed":on,className:`rounded-md border px-2 py-0.5 text-xs ${on?"bg-danger-soft text-danger line-through":"hover:bg-accent"}`,children:d},d)}))}))}),
    f.jsx(al,{title:`Filing rules (${(get("rules",[])||[]).length})`,children:SFx("div",null,
      SFx("p",{className:"mb-3 text-sm text-muted-foreground"},"Checked top to bottom before the model. The first matching rule decides. Takes effect when you save."),
      f.jsx(SFrules,{rules:get("rules",[]),onChange:v=>set("rules",v),dests}))}),
    f.jsx(al,{title:"Model (Ollama)",children:SFx("div",{style:{marginTop:"-12px"}},
      f.jsx(SFrow,{label:"Model",help:"Predicts destinations for files no rule matches.",children:f.jsx(SFmodel,{value:get("ollama.model",""),onChange:v=>set("ollama.model",v),models:meta.models})}),
      f.jsx(SFrow,{label:"Ollama address",children:f.jsx("input",{value:get("ollama.url",""),onChange:e=>set("ollama.url",e.target.value),className:SFinput+" font-mono",style:{maxWidth:"320px"}})}),
      f.jsx(SFrow,{label:"Thinking",help:"Off is much faster with Qwen3. Ignored by models without it.",children:f.jsx(SFtoggle,{value:get("ollama.think",!1),onChange:v=>set("ollama.think",v),label:"Let the model think before answering"})}),
      f.jsx(SFrow,{label:"Learn from my filing",help:"Your recent filing decisions shown to the model as examples. 0 = none.",children:f.jsx(SFnum,{value:get("history_examples",15),onChange:v=>set("history_examples",v),min:0,max:100,suffix:"examples"})}),
      f.jsx(SFrow,{label:"Timeouts",children:SFx("div",{className:"flex flex-wrap gap-4"},
        SFx("span",{className:"text-sm"},"Per file ",f.jsx(SFnum,{value:get("ollama.timeout_seconds",120),onChange:v=>set("ollama.timeout_seconds",v),min:10,max:1800,suffix:"s"})),
        SFx("span",{className:"text-sm"},"Wait after boot ",f.jsx(SFnum,{value:get("ollama.startup_wait_seconds",300),onChange:v=>set("ollama.startup_wait_seconds",v),min:0,max:7200,suffix:"s"})))}))}),
    f.jsx(al,{title:"Watching",children:SFx("div",{style:{marginTop:"-12px"}},
      f.jsx(SFrow,{label:"Wait for downloads to finish",help:"A file must stop growing for this long before it's read.",children:f.jsx(SFnum,{value:get("settle_seconds",5),onChange:v=>set("settle_seconds",v),min:1,max:600,suffix:"seconds"})}),
      f.jsx(SFrow,{label:"Catch up after downtime",help:"On start, predict files that arrived in the last N days while the agent was off.",children:f.jsx(SFnum,{value:get("catch_up_days",7),onChange:v=>set("catch_up_days",v),min:0,max:365,suffix:"days"})}),
      f.jsx(SFrow,{label:"Sweep for missed filings",children:f.jsx(SFnum,{value:get("reconcile_minutes",30),onChange:v=>set("reconcile_minutes",v),min:1,max:1440,suffix:"minutes"})}),
      f.jsx(SFrow,{label:"Ignore files matching",help:"One pattern per line, e.g. *.tmp",children:f.jsx(SFlines,{value:get("ignore_patterns",[]),onChange:v=>set("ignore_patterns",v),rows:5})}))}),
    f.jsx(al,{title:"Cleanup",children:SFx("div",{style:{marginTop:"-12px"}},
      f.jsx(SFrow,{label:"Scan automatically",help:"0 = only when you click Scan now.",children:f.jsx(SFnum,{value:get("cleanup.scan_hours",dc("scan_hours")),onChange:v=>set("cleanup.scan_hours",v),min:0,max:720,suffix:"hours"})}),
      f.jsx(SFrow,{label:"List installers and programs older than",children:f.jsx(SFnum,{value:get("cleanup.installer_days",dc("installer_days")),onChange:v=>set("cleanup.installer_days",v),min:1,max:3650,suffix:"days"})}),
      f.jsx(SFrow,{label:"List driver packages older than",children:f.jsx(SFnum,{value:get("cleanup.driver_days",dc("driver_days")),onChange:v=>set("cleanup.driver_days",v),min:1,max:3650,suffix:"days"})}),
      f.jsx(SFrow,{label:"Old, unopened files",help:"Listed for review only. Documents are never flagged on age.",children:f.jsx(SFnum,{value:get("cleanup.stale_days",dc("stale_days")),onChange:v=>set("cleanup.stale_days",v),min:1,max:3650,suffix:"days"})}),
      f.jsx(SFrow,{label:"PARA duplicates",children:f.jsx(SFtoggle,{value:get("cleanup.para_duplicates",dc("para_duplicates")),onChange:v=>set("cleanup.para_duplicates",v),label:"Also report duplicates inside the PARA tree (information only)"})}))}),
    f.jsx(al,{title:"Search",children:SFx("div",{style:{marginTop:"-12px"}},
      f.jsx(SFrow,{label:"Search index",children:f.jsx(SFtoggle,{value:!searchOff,onChange:v=>set("search.enabled",v),label:"Index watched folders and the PARA root for the Search page"})}),
      !searchOff&&f.jsx(SFrow,{label:"Embedding model",help:"Changing it rebuilds the whole index.",warn:(orig?.search?.model??ds("model"))!==get("search.model",ds("model"))?"Saving will rebuild the index from scratch (about an hour).":null,children:f.jsx(SFmodel,{value:get("search.model",ds("model")),onChange:v=>set("search.model",v),models:meta.models,embed:!0})}),
      !searchOff&&f.jsx(SFrow,{label:"Also index",help:"Extra folders, besides the watched folders and PARA root.",children:f.jsx(SFpaths,{value:get("search.extra_folders",[]),onChange:v=>set("search.extra_folders",v)})}),
      !searchOff&&f.jsx(SFrow,{label:"Skip paths matching",help:"One pattern per line, e.g. *\\node_modules\\*",children:f.jsx(SFlines,{value:get("search.exclude_globs",[]),onChange:v=>set("search.exclude_globs",v),rows:3})}),
      !searchOff&&f.jsx(SFrow,{label:"Minimum meaning match",help:"Meaning-only results below this are hidden. Raise if you see weak matches; lower if good ones are missing.",children:f.jsx(SFnum,{value:get("search.min_similarity",ds("min_similarity")),onChange:v=>set("search.min_similarity",v),min:0,max:1,step:.01})}),
      !searchOff&&f.jsx(SFrow,{label:"Re-check folders every",help:"New and changed files are also picked up within seconds.",children:f.jsx(SFnum,{value:get("search.sweep_minutes",ds("sweep_minutes")),onChange:v=>set("search.sweep_minutes",v),min:1,max:1440,suffix:"minutes"})}))}),
    f.jsx(al,{title:"Auto-filing (Phase 3)",children:SFx("div",{style:{marginTop:"-12px"}},
      f.jsx(SFrow,{label:"Auto-filing",help:"Files go automatically only into folders your own Inbox decisions have proven. Every auto-move can be undone.",children:f.jsx(SFtoggle,{value:get("autofile.enabled",dA("enabled")),onChange:v=>set("autofile.enabled",v),label:"File automatically into proven folders"})}),
      f.jsx(SFrow,{label:"A folder is proven after",help:"Your decisions on the Inbox page where that folder was the first suggestion.",children:SFx("div",{className:"flex flex-wrap gap-4"},
        SFx("span",{className:"text-sm"},f.jsx(SFnum,{value:get("autofile.min_decisions",dA("min_decisions")),onChange:v=>set("autofile.min_decisions",v),min:5,max:500,suffix:"decisions"})),
        SFx("span",{className:"text-sm"},"with ",f.jsx(SFnum,{value:get("autofile.min_rate",dA("min_rate")),onChange:v=>set("autofile.min_rate",v),min:.5,max:1,step:.01,suffix:"agreement (0–1)"})))}),
      f.jsx(SFrow,{label:"Similar-document suggestions",help:"Rule and file-name matches qualify regardless.",children:f.jsx(SFnum,{value:get("autofile.min_score",dA("min_score")),onChange:v=>set("autofile.min_score",v),min:.5,max:1,step:.01,suffix:"minimum strength (0–1)"})}),
      f.jsx(SFrow,{label:"Leave new downloads alone for",children:f.jsx(SFnum,{value:get("autofile.delay_minutes",dA("delay_minutes")),onChange:v=>set("autofile.delay_minutes",v),min:1,max:1440,suffix:"minutes"})}))}),
    f.jsx(al,{title:"OCR (scanned files)",children:SFx("div",{style:{marginTop:"-12px"}},
      f.jsx(SFrow,{label:"Read scanned files",help:"Uses the OCR built into Windows. Scanned PDFs, images and Word files that are only screenshots become searchable and get better filing predictions. Password-protected PDFs are never opened.",
        children:f.jsx(SFtoggle,{value:get("ocr.enabled",dO("enabled")),onChange:v=>set("ocr.enabled",v),label:"Use OCR"})}),
      get("ocr.enabled",dO("enabled"))!==!1&&f.jsx(SFrow,{label:"Pages per scanned PDF",help:"Later pages are skipped. More pages = slower indexing.",children:f.jsx(SFnum,{value:get("ocr.max_pdf_pages",dO("max_pdf_pages")),onChange:v=>set("ocr.max_pdf_pages",v),min:1,max:200,suffix:"pages"})}),
      get("ocr.enabled",dO("enabled"))!==!1&&f.jsx(SFrow,{label:"Skip images smaller than",help:"Small images are mostly icons and logos.",children:f.jsx(SFnum,{value:get("ocr.min_image_kb",dO("min_image_kb")),onChange:v=>set("ocr.min_image_kb",v),min:0,max:10000,suffix:"KB"})}),
      f.jsx(SFrow,{label:"Test",help:"Reads a generated test image and a test scanned PDF. Takes a few seconds.",children:f.jsx(SFocrTest,{})}))}),
    f.jsx(al,{title:"Interface",children:SFx("div",{style:{marginTop:"-12px"}},
      f.jsx(SFrow,{label:"Port",help:"http://127.0.0.1:<port>. Only this PC can reach it. Needs a restart.",children:f.jsx(SFnum,{value:get("ui.port",8765),onChange:v=>set("ui.port",v),min:1024,max:65535})}),
      f.jsx(SFrow,{label:"Config file",children:SFx("span",{className:"font-mono text-xs"},meta.config_path," · previous version kept as config.yaml.bak")}))}),
    dirty&&SFx("div",{className:"panel flex flex-wrap items-center gap-3 px-4 py-2",style:{position:"sticky",bottom:"12px",boxShadow:"0 4px 18px rgba(0,0,0,.18)"}},
      SFx("span",{className:"text-sm"},"You have unsaved changes."),
      SFx("span",{className:"ml-auto flex gap-2"},SFx(uc,{onClick:()=>{setForm(SFclone(orig));setRes(null)},disabled:saving},"Discard"),SFx(uc,{variant:"primary",onClick:save,disabled:saving},saving?"Saving…":"Save changes"))));
}
