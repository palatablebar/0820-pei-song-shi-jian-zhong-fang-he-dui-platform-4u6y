import {element} from './client.js';

function zone(target, className, text) {
  const box = element('div', undefined, {class:className});
  if (text) box.append(element('span',text));
  target.append(box);
  return box;
}

function fill(layer, value, max, label) {
  const mark = zone(layer, 'mark-piece', label);
  mark.style.setProperty('--part', `${Math.max(0,Math.min(100,100*value/Math.max(1,max)))}%`);
  return mark;
}

export function visualize(report, selected) {
  const target = document.querySelector('#visual');
  const row = report.cases?.find(item=>item.case===selected && item.measure);
  target.replaceChildren();
  if (!row) { target.append(element('p','该分组暂无计算值')); return; }
  const {evidence:e, value, expected, unit} = row.measure;
  render(target, e, value, expected, unit);
}

function render(target,e,value,expected,unit) {
  const log=zone(target,'replay-log');
  Object.entries(e.live).forEach(([id,quantity])=> zone(log,'replay-event replay-live',`UPSERT ${id} → ${quantity} 件`));
  Object.entries(e.tombstones).forEach(([id,seq])=> zone(log,'replay-event replay-delete',`DELETE ${id} @ ${seq}`));
  if(!log.children.length) log.append(element('p','当前水位没有有效事件'));
}
