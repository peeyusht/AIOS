/* Inbox page (Phase 2, suggest mode): files waiting in Downloads with filing suggestions, "File it", Undo.
   Uses the bundle's helpers: f, Z, uc, al, Ba, Yn, Gf, He, cc, Wl, cm, Qt, Ya, d1 (refresh icon), SFx. */
const SFinboxIcon=Qt("inbox",[["polyline",{points:"22 12 16 12 14 15 10 15 8 12 2 12",key:"i1"}],["path",{d:"M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z",key:"i2"}]]);
const SFsrcText={rule:"rule",similar:"like your filed docs",model:"model's guess"};
function SFconf(score){if(score==null)return null;const pct=Math.round(score*100);const tone=score>=.95?"success":score>=.7?"info":"warning";return f.jsx(Ba,{tone,children:`${pct}%`})}
function SFinboxItem({it,dests,onDone,setMsg}){
  const first=it.candidates?.[0];
  const[sel,setSel]=Z.useState(first?.folder??""),[other,setOther]=Z.useState(!1),[busy,setBusy]=Z.useState(!1);
  const choose=async()=>{if(!sel)return;setBusy(!0);setMsg(null);
    const c=(it.candidates||[]).find(x=>x.folder===sel);
    try{const r=await cm("/api/inbox/file",{path:it.path,folder:sel,size:it.size,source:c?.source??"manual",rank:c?.rank??0,top_folder:first?.folder??null,top_score:first?.score??null});
      if(r.ok){onDone({text:`Filed ${it.name} → ${sel}${r.renamed?` (as ${r.dest.split(/[\\/]/).pop()})`:""}`,id:r.id})}else setMsg(r.message)}catch(e){setMsg(String(e?.message??e))}setBusy(!1)};
  const skip=async()=>{setBusy(!0);try{await cm("/api/inbox/dismiss",{path:it.path});onDone(null)}catch(e){setMsg(String(e))}setBusy(!1)};
  const show=()=>cm("/api/cleanup/reveal",{path:it.path}).catch(()=>{});
  return SFx("li",{className:"panel px-4 py-3"},
    SFx("div",{className:"flex flex-wrap items-start gap-x-3 gap-y-1"},
      SFx("div",{className:"min-w-0 flex-1"},
        SFx("div",{className:"truncate font-medium",title:it.path},it.name),
        SFx("div",{className:"text-xs text-muted-foreground"},He(it.size)," · ",cc(it.modified))),
      it.cleanup&&f.jsx(Ba,{tone:"warning",children:it.cleanup.category==="duplicate_of_filed"?"Already filed (duplicate)":it.cleanup.category==="partial_download"?"Partial download":"Cleanup: "+it.cleanup.level}),
      it.duplicate&&!it.cleanup&&f.jsx(Ba,{tone:"warning",children:`Same as a file in ${it.duplicate.folder}`})),
    !it.ready&&SFx("p",{className:"mt-2 text-xs text-muted-foreground"},"Still being read; suggestions from similar files appear once it's indexed."),
    SFx("div",{className:"mt-2 flex flex-wrap items-center gap-2"},
      (it.candidates??[]).map(c=>f.jsx("button",{onClick:()=>{setSel(c.folder);setOther(!1)},"aria-pressed":sel===c.folder,title:c.why,
        className:`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-sm ${sel===c.folder?"bg-accent font-medium":"hover:bg-accent"}`,
        children:[f.jsx("span",{className:"font-mono text-xs",children:c.folder},"f"),c.score!=null&&SFconf(c.score),
          SFx("span",{key:"s",className:"text-xs text-muted-foreground"},SFsrcText[c.source]??c.source,c.model_agrees?" · model agrees":""),
          c.exists===!1&&SFx("span",{key:"x",className:"text-xs text-danger"},"(folder missing)")]},c.folder)),
      (it.candidates??[]).length===0&&SFx("span",{className:"text-sm text-muted-foreground"},"No suggestion yet."),
      other?SFx("select",{autoFocus:!0,value:sel,onChange:e=>setSel(e.target.value),className:"rounded-md border bg-card px-2 py-1 text-sm",style:{maxWidth:"320px"}},
          f.jsx("option",{value:"",children:"Choose a folder…"}),dests.map(d=>f.jsx("option",{value:d,children:d},d))):
        f.jsx("button",{onClick:()=>setOther(!0),className:"rounded-md border px-2 py-1 text-sm text-muted-foreground hover:bg-accent",children:"Other folder…"})),
    SFx("div",{className:"mt-2 flex flex-wrap items-center gap-2"},
      SFx(uc,{variant:"primary",onClick:choose,disabled:busy||!sel||(it.candidates||[]).some(c=>c.folder===sel&&c.exists===!1)},busy?"Filing…":`File it${sel?` → ${sel}`:""}`),
      SFx(uc,{onClick:skip,disabled:busy,title:"Hide this file from the inbox (it stays in Downloads)"},"Leave it"),
      SFx(uc,{onClick:show},"Show")));
}
function SFinbox(){
  const[off,setOff]=Z.useState(0),[msg,setMsg]=Z.useState(null),[last,setLast]=Z.useState(null),[tick,setTick]=Z.useState(0);
  const{data:d,error:err,reload}=Ya(()=>Wl(`/api/inbox?offset=${off}&limit=25`),3e4,[off,tick]);
  const{data:mv,reload:reloadMoves}=Ya(()=>Wl("/api/moves"),3e4,[tick]);
  const done=r=>{if(r)setLast(r);setTick(t=>t+1)};
  const undo=async id=>{setMsg(null);try{const r=await cm("/api/moves/undo",{id});if(r.ok){setLast({text:`Undone: back in ${r.restored}`});setTick(t=>t+1)}else setMsg(r.message)}catch(e){setMsg(String(e))}};
  const fb=mv?.feedback;
  return SFx("div",{className:"space-y-4"},
    SFx("div",{className:"flex flex-wrap items-center gap-3"},
      SFx("h1",{className:"text-lg font-semibold"},"Inbox"),
      SFx("span",{className:"text-xs text-muted-foreground"},d?`${d.total} file${d.total===1?"":"s"} waiting in Downloads${d.examples?` · suggestions learned from ${d.examples.examples.toLocaleString()} filed documents in ${d.examples.folders} folders`:""}`:"Loading…"),
      SFx(uc,{className:"ml-auto",onClick:()=>setTick(t=>t+1)},SFx(d1,{className:"h-4 w-4"}),"Refresh")),
    SFx("div",{className:"flex items-start gap-2 rounded-md border border-info bg-info-soft px-3 py-2 text-sm text-info"},SFx(u1,{className:"mt-0.5 h-4 w-4 shrink-0"}),
      SFx("span",null,"Files move only when you click ",SFx("b",null,"File it"),". Every move can be undone below. The percentage is how strongly your already-filed documents point to that folder. Tested on your own filed documents: ",SFx("b",null,"95%+")," was right 94 times in 100, 50–70% about 7 in 10, and under 50% only 1 in 3, so check those.")),
    err&&f.jsx(Yn,{error:err}),
    msg&&SFx("div",{role:"alert",className:"rounded-md border border-warning bg-warning-soft px-3 py-2 text-sm text-warning"},msg),
    last&&SFx("div",{role:"status",className:"flex flex-wrap items-center gap-3 rounded-md border border-success bg-success-soft px-3 py-2 text-sm text-success"},last.text,last.id&&SFx(uc,{onClick:()=>undo(last.id)},"Undo")),
    d&&d.items.length===0&&f.jsx(Gf,{title:"Inbox is empty",children:"Nothing waiting in Downloads."}),
    d&&d.items.length>0&&SFx("ol",{className:"space-y-2"},d.items.map(it=>f.jsx(SFinboxItem,{it,dests:d.destinations??[],onDone:done,setMsg},it.path+it.size))),
    d&&d.total>25&&SFx("div",{className:"flex items-center gap-2"},
      SFx(uc,{onClick:()=>setOff(Math.max(0,off-25)),disabled:off===0},"← Newer"),
      SFx("span",{className:"text-sm text-muted-foreground"},`${off+1}–${Math.min(off+25,d.total)} of ${d.total}`),
      SFx(uc,{onClick:()=>setOff(off+25),disabled:off+25>=d.total},"Older →")),
    f.jsx(al,{title:"Your filing so far",children:!fb||fb.moves===0?SFx("p",{className:"text-sm text-muted-foreground"},"No files filed from here yet."):
      SFx("div",{className:"space-y-2 text-sm"},
        SFx("p",null,`${fb.moves} file${fb.moves===1?"":"s"} filed · the first suggestion was right ${fb.top_accepted} time${fb.top_accepted===1?"":"s"} (${Math.round(fb.rate*100)}%).`),
        SFx("table",{className:"w-full text-xs"},SFx("thead",{className:"text-left text-muted-foreground"},SFx("tr",null,f.jsx("th",{className:"py-1 font-medium",children:"Suggested first"}),f.jsx("th",{className:"font-medium",children:"Times"}),f.jsx("th",{className:"font-medium",children:"You agreed"}))),
          f.jsx("tbody",{children:fb.per_folder.slice(0,15).map(r=>SFx("tr",{key:r.folder,className:"border-t"},f.jsx("td",{className:"py-1 font-mono",children:r.folder}),f.jsx("td",{children:r.n}),f.jsx("td",{children:`${r.accepted} (${Math.round(r.accepted/r.n*100)}%)`})))})))}),
    f.jsx(al,{title:"Recent moves",children:!mv||mv.journal.length===0?SFx("p",{className:"text-sm text-muted-foreground"},"None yet."):
      SFx("ul",{className:"space-y-1 text-sm"},mv.journal.slice(0,30).map(m=>SFx("li",{key:m.id,className:"flex flex-wrap items-center gap-2"},
        SFx("span",{className:"text-xs text-muted-foreground"},cc(m.ts)),
        SFx("span",{className:"min-w-0 flex-1 truncate",title:`${m.src} → ${m.dest}`},m.src.split(/[\\/]/).pop()," → ",f.jsx("span",{className:"font-mono text-xs",children:m.folder})),
        m.status==="moved"?SFx(uc,{onClick:()=>undo(m.id)},"Undo"):f.jsx(Ba,{tone:"muted",children:m.note?`undone · ${m.note}`:"undone"}))))}));
}
