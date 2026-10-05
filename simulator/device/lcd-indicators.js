// LCD row 0 contains hardware segment controls, not dot-matrix pixels.
// These 18 masks and 288-pixel slots match the original host's status renderer.
// Unassigned row-0 bits remain in the raw C snapshot and have no invented label.
const indicator = (id,label,ariaLabel,byte,mask,left,width,boxed=false) =>
 Object.freeze({id,label,ariaLabel,byte,mask,left,width,boxed});

export const LCD_INDICATORS = Object.freeze([
 indicator('S','S','Shift modifier',0,0x10,0,8,true),
 indicator('A','A','Alpha modifier',0,0x04,8,11,true),
 indicator('M','M','Memory indicator',1,0x10,19,11),
 indicator('STO','STO','Store modifier',1,0x02,30,19),
 indicator('RCL','RCL','Recall modifier',2,0x40,49,18),
 indicator('STAT','STAT','Statistics mode',3,0x40,67,24),
 indicator('CMPLX','CMPLX','Complex mode',4,0x80,91,31),
 indicator('MAT','MAT','Matrix mode',5,0x40,122,19),
 indicator('VCT','VCT','Vector mode',5,0x02,141,18),
 indicator('D','D','Degrees angle unit',7,0x20,159,11,true),
 indicator('R','R','Radians angle unit',7,0x02,170,9,true),
 indicator('G','G','Gradians angle unit',8,0x10,179,10,true),
 indicator('FIX','FIX','Fixed decimal format',8,0x01,189,17),
 indicator('SCI','SCI','Scientific format',9,0x20,206,15),
 indicator('Math','Math','Natural display mode',10,0x40,221,26),
 indicator('DOWN','▼','Down arrow',10,0x08,247,11),
 indicator('UP','▲','Up arrow',11,0x80,258,9),
 indicator('Disp','Disp','Display indicator',11,0x10,267,21),
]);

/** Decode only the first 12 raw C framebuffer bytes; left/width use 288px units. */
export function decodeLcdIndicators(bytes) {
 if (!bytes || bytes.length < 12) throw new TypeError('LCD segment controls require 12 bytes.');
 for (let index=0;index<12;index++) {
  if (!Number.isInteger(bytes[index]) || bytes[index] < 0 || bytes[index] > 255) {
   throw new TypeError('LCD segment controls must be unsigned bytes.');
  }
 }
 return LCD_INDICATORS.map(item => ({...item,active:!!(bytes[item.byte] & item.mask)}));
}

const indicatorElements = new WeakMap();

/** Create the status-strip elements once; no engine or DOM is needed to decode. */
export function initLcdIndicators(element) {
 if (!element?.ownerDocument) throw new TypeError('LCD indicator container is missing.');
 if (indicatorElements.has(element)) return indicatorElements.get(element);
 const spans = LCD_INDICATORS.map(item => {
  const span = element.ownerDocument.createElement('span');
  span.className = 'lcd-indicator'+(item.boxed ? ' boxed' : '');
  span.dataset.indicator = item.id;
  span.textContent = item.label;
  span.setAttribute('role','img');
  span.setAttribute('aria-label',item.ariaLabel);
  span.style.setProperty('--indicator-left',(item.left/288*100)+'%');
  span.style.setProperty('--indicator-width',(item.width/288*100)+'%');
  span.hidden = true;
  return span;
 });
 element.replaceChildren(...spans);
 indicatorElements.set(element,spans);
 return spans;
}

/** Render directly from hardware flags, without inferring state from key input. */
export function renderLcdIndicators(element,bytes) {
 const decoded = decodeLcdIndicators(bytes);
 const spans = initLcdIndicators(element);
 decoded.forEach((item,index) => { spans[index].hidden = !item.active; });
 return decoded;
}
