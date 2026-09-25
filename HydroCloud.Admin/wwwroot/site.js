for (const [parentId, childId] of [['Station_Basin','Station_SubBasin'],['Station_State','Station_Municipality']]) {
  const parent=document.getElementById(parentId), child=document.getElementById(childId);
  if (!parent || !child) continue;
  const filter=()=>{ for(const option of child.options) { const invalid=!!option.value && option.dataset.parent!==parent.value; option.hidden=invalid; option.disabled=invalid; } };
  parent.addEventListener('change',()=>{filter(); if(child.selectedOptions[0]?.disabled) child.value='';});
  filter();
}
