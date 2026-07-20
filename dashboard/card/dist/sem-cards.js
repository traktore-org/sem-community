const e=globalThis,t=e.ShadowRoot&&(void 0===e.ShadyCSS||e.ShadyCSS.nativeShadow)&&"adoptedStyleSheets"in Document.prototype&&"replace"in CSSStyleSheet.prototype,i=Symbol(),s=new WeakMap;let r=class{constructor(e,t,s){if(this._$cssResult$=!0,s!==i)throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");this.cssText=e,this.t=t}get styleSheet(){let e=this.o;const i=this.t;if(t&&void 0===e){const t=void 0!==i&&1===i.length;t&&(e=s.get(i)),void 0===e&&((this.o=e=new CSSStyleSheet).replaceSync(this.cssText),t&&s.set(i,e))}return e}toString(){return this.cssText}};const a=(e,...t)=>{const s=1===e.length?e[0]:t.reduce((t,i,s)=>t+(e=>{if(!0===e._$cssResult$)return e.cssText;if("number"==typeof e)return e;throw Error("Value passed to 'css' function must be a 'css' function result: "+e+". Use 'unsafeCSS' to pass non-literal values, but take care to ensure page security.")})(i)+e[s+1],e[0]);return new r(s,e,i)},o=t?e=>e:e=>e instanceof CSSStyleSheet?(e=>{let t="";for(const i of e.cssRules)t+=i.cssText;return(e=>new r("string"==typeof e?e:e+"",void 0,i))(t)})(e):e,{is:n,defineProperty:l,getOwnPropertyDescriptor:c,getOwnPropertyNames:d,getOwnPropertySymbols:p,getPrototypeOf:h}=Object,_=globalThis,g=_.trustedTypes,u=g?g.emptyScript:"",f=_.reactiveElementPolyfillSupport,m=(e,t)=>e,y={toAttribute(e,t){switch(t){case Boolean:e=e?u:null;break;case Object:case Array:e=null==e?e:JSON.stringify(e)}return e},fromAttribute(e,t){let i=e;switch(t){case Boolean:i=null!==e;break;case Number:i=null===e?null:Number(e);break;case Object:case Array:try{i=JSON.parse(e)}catch(e){i=null}}return i}},v=(e,t)=>!n(e,t),x={attribute:!0,type:String,converter:y,reflect:!1,useDefault:!1,hasChanged:v};Symbol.metadata??=Symbol("metadata"),_.litPropertyMetadata??=new WeakMap;let b=class extends HTMLElement{static addInitializer(e){this._$Ei(),(this.l??=[]).push(e)}static get observedAttributes(){return this.finalize(),this._$Eh&&[...this._$Eh.keys()]}static createProperty(e,t=x){if(t.state&&(t.attribute=!1),this._$Ei(),this.prototype.hasOwnProperty(e)&&((t=Object.create(t)).wrapped=!0),this.elementProperties.set(e,t),!t.noAccessor){const i=Symbol(),s=this.getPropertyDescriptor(e,i,t);void 0!==s&&l(this.prototype,e,s)}}static getPropertyDescriptor(e,t,i){const{get:s,set:r}=c(this.prototype,e)??{get(){return this[t]},set(e){this[t]=e}};return{get:s,set(t){const a=s?.call(this);r?.call(this,t),this.requestUpdate(e,a,i)},configurable:!0,enumerable:!0}}static getPropertyOptions(e){return this.elementProperties.get(e)??x}static _$Ei(){if(this.hasOwnProperty(m("elementProperties")))return;const e=h(this);e.finalize(),void 0!==e.l&&(this.l=[...e.l]),this.elementProperties=new Map(e.elementProperties)}static finalize(){if(this.hasOwnProperty(m("finalized")))return;if(this.finalized=!0,this._$Ei(),this.hasOwnProperty(m("properties"))){const e=this.properties,t=[...d(e),...p(e)];for(const i of t)this.createProperty(i,e[i])}const e=this[Symbol.metadata];if(null!==e){const t=litPropertyMetadata.get(e);if(void 0!==t)for(const[e,i]of t)this.elementProperties.set(e,i)}this._$Eh=new Map;for(const[e,t]of this.elementProperties){const i=this._$Eu(e,t);void 0!==i&&this._$Eh.set(i,e)}this.elementStyles=this.finalizeStyles(this.styles)}static finalizeStyles(e){const t=[];if(Array.isArray(e)){const i=new Set(e.flat(1/0).reverse());for(const e of i)t.unshift(o(e))}else void 0!==e&&t.push(o(e));return t}static _$Eu(e,t){const i=t.attribute;return!1===i?void 0:"string"==typeof i?i:"string"==typeof e?e.toLowerCase():void 0}constructor(){super(),this._$Ep=void 0,this.isUpdatePending=!1,this.hasUpdated=!1,this._$Em=null,this._$Ev()}_$Ev(){this._$ES=new Promise(e=>this.enableUpdating=e),this._$AL=new Map,this._$E_(),this.requestUpdate(),this.constructor.l?.forEach(e=>e(this))}addController(e){(this._$EO??=new Set).add(e),void 0!==this.renderRoot&&this.isConnected&&e.hostConnected?.()}removeController(e){this._$EO?.delete(e)}_$E_(){const e=new Map,t=this.constructor.elementProperties;for(const i of t.keys())this.hasOwnProperty(i)&&(e.set(i,this[i]),delete this[i]);e.size>0&&(this._$Ep=e)}createRenderRoot(){const i=this.shadowRoot??this.attachShadow(this.constructor.shadowRootOptions);return((i,s)=>{if(t)i.adoptedStyleSheets=s.map(e=>e instanceof CSSStyleSheet?e:e.styleSheet);else for(const t of s){const s=document.createElement("style"),r=e.litNonce;void 0!==r&&s.setAttribute("nonce",r),s.textContent=t.cssText,i.appendChild(s)}})(i,this.constructor.elementStyles),i}connectedCallback(){this.renderRoot??=this.createRenderRoot(),this.enableUpdating(!0),this._$EO?.forEach(e=>e.hostConnected?.())}enableUpdating(e){}disconnectedCallback(){this._$EO?.forEach(e=>e.hostDisconnected?.())}attributeChangedCallback(e,t,i){this._$AK(e,i)}_$ET(e,t){const i=this.constructor.elementProperties.get(e),s=this.constructor._$Eu(e,i);if(void 0!==s&&!0===i.reflect){const r=(void 0!==i.converter?.toAttribute?i.converter:y).toAttribute(t,i.type);this._$Em=e,null==r?this.removeAttribute(s):this.setAttribute(s,r),this._$Em=null}}_$AK(e,t){const i=this.constructor,s=i._$Eh.get(e);if(void 0!==s&&this._$Em!==s){const e=i.getPropertyOptions(s),r="function"==typeof e.converter?{fromAttribute:e.converter}:void 0!==e.converter?.fromAttribute?e.converter:y;this._$Em=s;const a=r.fromAttribute(t,e.type);this[s]=a??this._$Ej?.get(s)??a,this._$Em=null}}requestUpdate(e,t,i,s=!1,r){if(void 0!==e){const a=this.constructor;if(!1===s&&(r=this[e]),i??=a.getPropertyOptions(e),!((i.hasChanged??v)(r,t)||i.useDefault&&i.reflect&&r===this._$Ej?.get(e)&&!this.hasAttribute(a._$Eu(e,i))))return;this.C(e,t,i)}!1===this.isUpdatePending&&(this._$ES=this._$EP())}C(e,t,{useDefault:i,reflect:s,wrapped:r},a){i&&!(this._$Ej??=new Map).has(e)&&(this._$Ej.set(e,a??t??this[e]),!0!==r||void 0!==a)||(this._$AL.has(e)||(this.hasUpdated||i||(t=void 0),this._$AL.set(e,t)),!0===s&&this._$Em!==e&&(this._$Eq??=new Set).add(e))}async _$EP(){this.isUpdatePending=!0;try{await this._$ES}catch(e){Promise.reject(e)}const e=this.scheduleUpdate();return null!=e&&await e,!this.isUpdatePending}scheduleUpdate(){return this.performUpdate()}performUpdate(){if(!this.isUpdatePending)return;if(!this.hasUpdated){if(this.renderRoot??=this.createRenderRoot(),this._$Ep){for(const[e,t]of this._$Ep)this[e]=t;this._$Ep=void 0}const e=this.constructor.elementProperties;if(e.size>0)for(const[t,i]of e){const{wrapped:e}=i,s=this[t];!0!==e||this._$AL.has(t)||void 0===s||this.C(t,void 0,i,s)}}let e=!1;const t=this._$AL;try{e=this.shouldUpdate(t),e?(this.willUpdate(t),this._$EO?.forEach(e=>e.hostUpdate?.()),this.update(t)):this._$EM()}catch(t){throw e=!1,this._$EM(),t}e&&this._$AE(t)}willUpdate(e){}_$AE(e){this._$EO?.forEach(e=>e.hostUpdated?.()),this.hasUpdated||(this.hasUpdated=!0,this.firstUpdated(e)),this.updated(e)}_$EM(){this._$AL=new Map,this.isUpdatePending=!1}get updateComplete(){return this.getUpdateComplete()}getUpdateComplete(){return this._$ES}shouldUpdate(e){return!0}update(e){this._$Eq&&=this._$Eq.forEach(e=>this._$ET(e,this[e])),this._$EM()}updated(e){}firstUpdated(e){}};b.elementStyles=[],b.shadowRootOptions={mode:"open"},b[m("elementProperties")]=new Map,b[m("finalized")]=new Map,f?.({ReactiveElement:b}),(_.reactiveElementVersions??=[]).push("2.1.2");const $=globalThis,w=e=>e,k=$.trustedTypes,S=k?k.createPolicy("lit-html",{createHTML:e=>e}):void 0,C="$lit$",z=`lit$${Math.random().toFixed(9).slice(2)}$`,M="?"+z,E=`<${M}>`,D=document,F=()=>D.createComment(""),I=e=>null===e||"object"!=typeof e&&"function"!=typeof e,B=Array.isArray,N="[ \t\n\f\r]",A=/<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g,T=/-->/g,P=/>/g,R=RegExp(`>|${N}(?:([^\\s"'>=/]+)(${N}*=${N}*(?:[^ \t\n\f\r"'\`<>=]|("|')|))|$)`,"g"),L=/'/g,O=/"/g,U=/^(?:script|style|textarea|title)$/i,H=e=>(t,...i)=>({_$litType$:e,strings:t,values:i}),W=H(1),j=H(2),G=Symbol.for("lit-noChange"),q=Symbol.for("lit-nothing"),K=new WeakMap,V=D.createTreeWalker(D,129);function Y(e,t){if(!B(e)||!e.hasOwnProperty("raw"))throw Error("invalid template strings array");return void 0!==S?S.createHTML(t):t}const X=(e,t)=>{const i=e.length-1,s=[];let r,a=2===t?"<svg>":3===t?"<math>":"",o=A;for(let t=0;t<i;t++){const i=e[t];let n,l,c=-1,d=0;for(;d<i.length&&(o.lastIndex=d,l=o.exec(i),null!==l);)d=o.lastIndex,o===A?"!--"===l[1]?o=T:void 0!==l[1]?o=P:void 0!==l[2]?(U.test(l[2])&&(r=RegExp("</"+l[2],"g")),o=R):void 0!==l[3]&&(o=R):o===R?">"===l[0]?(o=r??A,c=-1):void 0===l[1]?c=-2:(c=o.lastIndex-l[2].length,n=l[1],o=void 0===l[3]?R:'"'===l[3]?O:L):o===O||o===L?o=R:o===T||o===P?o=A:(o=R,r=void 0);const p=o===R&&e[t+1].startsWith("/>")?" ":"";a+=o===A?i+E:c>=0?(s.push(n),i.slice(0,c)+C+i.slice(c)+z+p):i+z+(-2===c?t:p)}return[Y(e,a+(e[i]||"<?>")+(2===t?"</svg>":3===t?"</math>":"")),s]};class Z{constructor({strings:e,_$litType$:t},i){let s;this.parts=[];let r=0,a=0;const o=e.length-1,n=this.parts,[l,c]=X(e,t);if(this.el=Z.createElement(l,i),V.currentNode=this.el.content,2===t||3===t){const e=this.el.content.firstChild;e.replaceWith(...e.childNodes)}for(;null!==(s=V.nextNode())&&n.length<o;){if(1===s.nodeType){if(s.hasAttributes())for(const e of s.getAttributeNames())if(e.endsWith(C)){const t=c[a++],i=s.getAttribute(e).split(z),o=/([.?@])?(.*)/.exec(t);n.push({type:1,index:r,name:o[2],strings:i,ctor:"."===o[1]?ie:"?"===o[1]?se:"@"===o[1]?re:te}),s.removeAttribute(e)}else e.startsWith(z)&&(n.push({type:6,index:r}),s.removeAttribute(e));if(U.test(s.tagName)){const e=s.textContent.split(z),t=e.length-1;if(t>0){s.textContent=k?k.emptyScript:"";for(let i=0;i<t;i++)s.append(e[i],F()),V.nextNode(),n.push({type:2,index:++r});s.append(e[t],F())}}}else if(8===s.nodeType)if(s.data===M)n.push({type:2,index:r});else{let e=-1;for(;-1!==(e=s.data.indexOf(z,e+1));)n.push({type:7,index:r}),e+=z.length-1}r++}}static createElement(e,t){const i=D.createElement("template");return i.innerHTML=e,i}}function J(e,t,i=e,s){if(t===G)return t;let r=void 0!==s?i._$Co?.[s]:i._$Cl;const a=I(t)?void 0:t._$litDirective$;return r?.constructor!==a&&(r?._$AO?.(!1),void 0===a?r=void 0:(r=new a(e),r._$AT(e,i,s)),void 0!==s?(i._$Co??=[])[s]=r:i._$Cl=r),void 0!==r&&(t=J(e,r._$AS(e,t.values),r,s)),t}class Q{constructor(e,t){this._$AV=[],this._$AN=void 0,this._$AD=e,this._$AM=t}get parentNode(){return this._$AM.parentNode}get _$AU(){return this._$AM._$AU}u(e){const{el:{content:t},parts:i}=this._$AD,s=(e?.creationScope??D).importNode(t,!0);V.currentNode=s;let r=V.nextNode(),a=0,o=0,n=i[0];for(;void 0!==n;){if(a===n.index){let t;2===n.type?t=new ee(r,r.nextSibling,this,e):1===n.type?t=new n.ctor(r,n.name,n.strings,this,e):6===n.type&&(t=new ae(r,this,e)),this._$AV.push(t),n=i[++o]}a!==n?.index&&(r=V.nextNode(),a++)}return V.currentNode=D,s}p(e){let t=0;for(const i of this._$AV)void 0!==i&&(void 0!==i.strings?(i._$AI(e,i,t),t+=i.strings.length-2):i._$AI(e[t])),t++}}class ee{get _$AU(){return this._$AM?._$AU??this._$Cv}constructor(e,t,i,s){this.type=2,this._$AH=q,this._$AN=void 0,this._$AA=e,this._$AB=t,this._$AM=i,this.options=s,this._$Cv=s?.isConnected??!0}get parentNode(){let e=this._$AA.parentNode;const t=this._$AM;return void 0!==t&&11===e?.nodeType&&(e=t.parentNode),e}get startNode(){return this._$AA}get endNode(){return this._$AB}_$AI(e,t=this){e=J(this,e,t),I(e)?e===q||null==e||""===e?(this._$AH!==q&&this._$AR(),this._$AH=q):e!==this._$AH&&e!==G&&this._(e):void 0!==e._$litType$?this.$(e):void 0!==e.nodeType?this.T(e):(e=>B(e)||"function"==typeof e?.[Symbol.iterator])(e)?this.k(e):this._(e)}O(e){return this._$AA.parentNode.insertBefore(e,this._$AB)}T(e){this._$AH!==e&&(this._$AR(),this._$AH=this.O(e))}_(e){this._$AH!==q&&I(this._$AH)?this._$AA.nextSibling.data=e:this.T(D.createTextNode(e)),this._$AH=e}$(e){const{values:t,_$litType$:i}=e,s="number"==typeof i?this._$AC(e):(void 0===i.el&&(i.el=Z.createElement(Y(i.h,i.h[0]),this.options)),i);if(this._$AH?._$AD===s)this._$AH.p(t);else{const e=new Q(s,this),i=e.u(this.options);e.p(t),this.T(i),this._$AH=e}}_$AC(e){let t=K.get(e.strings);return void 0===t&&K.set(e.strings,t=new Z(e)),t}k(e){B(this._$AH)||(this._$AH=[],this._$AR());const t=this._$AH;let i,s=0;for(const r of e)s===t.length?t.push(i=new ee(this.O(F()),this.O(F()),this,this.options)):i=t[s],i._$AI(r),s++;s<t.length&&(this._$AR(i&&i._$AB.nextSibling,s),t.length=s)}_$AR(e=this._$AA.nextSibling,t){for(this._$AP?.(!1,!0,t);e!==this._$AB;){const t=w(e).nextSibling;w(e).remove(),e=t}}setConnected(e){void 0===this._$AM&&(this._$Cv=e,this._$AP?.(e))}}class te{get tagName(){return this.element.tagName}get _$AU(){return this._$AM._$AU}constructor(e,t,i,s,r){this.type=1,this._$AH=q,this._$AN=void 0,this.element=e,this.name=t,this._$AM=s,this.options=r,i.length>2||""!==i[0]||""!==i[1]?(this._$AH=Array(i.length-1).fill(new String),this.strings=i):this._$AH=q}_$AI(e,t=this,i,s){const r=this.strings;let a=!1;if(void 0===r)e=J(this,e,t,0),a=!I(e)||e!==this._$AH&&e!==G,a&&(this._$AH=e);else{const s=e;let o,n;for(e=r[0],o=0;o<r.length-1;o++)n=J(this,s[i+o],t,o),n===G&&(n=this._$AH[o]),a||=!I(n)||n!==this._$AH[o],n===q?e=q:e!==q&&(e+=(n??"")+r[o+1]),this._$AH[o]=n}a&&!s&&this.j(e)}j(e){e===q?this.element.removeAttribute(this.name):this.element.setAttribute(this.name,e??"")}}class ie extends te{constructor(){super(...arguments),this.type=3}j(e){this.element[this.name]=e===q?void 0:e}}class se extends te{constructor(){super(...arguments),this.type=4}j(e){this.element.toggleAttribute(this.name,!!e&&e!==q)}}class re extends te{constructor(e,t,i,s,r){super(e,t,i,s,r),this.type=5}_$AI(e,t=this){if((e=J(this,e,t,0)??q)===G)return;const i=this._$AH,s=e===q&&i!==q||e.capture!==i.capture||e.once!==i.once||e.passive!==i.passive,r=e!==q&&(i===q||s);s&&this.element.removeEventListener(this.name,this,i),r&&this.element.addEventListener(this.name,this,e),this._$AH=e}handleEvent(e){"function"==typeof this._$AH?this._$AH.call(this.options?.host??this.element,e):this._$AH.handleEvent(e)}}class ae{constructor(e,t,i){this.element=e,this.type=6,this._$AN=void 0,this._$AM=t,this.options=i}get _$AU(){return this._$AM._$AU}_$AI(e){J(this,e)}}const oe={I:ee},ne=$.litHtmlPolyfillSupport;ne?.(Z,ee),($.litHtmlVersions??=[]).push("3.3.3");const le=globalThis;let ce=class extends b{constructor(){super(...arguments),this.renderOptions={host:this},this._$Do=void 0}createRenderRoot(){const e=super.createRenderRoot();return this.renderOptions.renderBefore??=e.firstChild,e}update(e){const t=this.render();this.hasUpdated||(this.renderOptions.isConnected=this.isConnected),super.update(e),this._$Do=((e,t,i)=>{const s=i?.renderBefore??t;let r=s._$litPart$;if(void 0===r){const e=i?.renderBefore??null;s._$litPart$=r=new ee(t.insertBefore(F(),e),e,void 0,i??{})}return r._$AI(e),r})(t,this.renderRoot,this.renderOptions)}connectedCallback(){super.connectedCallback(),this._$Do?.setConnected(!0)}disconnectedCallback(){super.disconnectedCallback(),this._$Do?.setConnected(!1)}render(){return G}};ce._$litElement$=!0,ce.finalized=!0,le.litElementHydrateSupport?.({LitElement:ce});const de=le.litElementPolyfillSupport;de?.({LitElement:ce}),(le.litElementVersions??=[]).push("4.2.2");const pe={solar:"#ff9800",gridImport:"#488fc2",gridExport:"#8353d1",batteryOut:"#4db6ac",battery:"#4db6ac",home:"#5BC8D8",ev:"#8DC892",inverter:"#96CAEE"},he=["#FF8A65","#AED581","#CE93D8","#64B5F6","#ff9800","#96CAEE"],_e="#86A9B4";function ge(e){if(null==e||isNaN(e))return"— W";return Math.abs(e)>=1e3?`${(e/1e3).toFixed(1)} kW`:`${Math.round(e)} W`}function ue(e,t){if(!e)return"—";try{return new Date(e).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit",timeZone:t||void 0})}catch(e){return"—"}}function fe(e){const t=Math.abs(e);if(t<=0)return 4;const i=4-.9*Math.log10(Math.max(t,1));return Math.max(.5,Math.min(4,i))}function me(e){if(!e)return"EUR";const t=e.states?.["sensor.sem_daily_costs"];return t?.attributes?.unit_of_measurement?t.attributes.unit_of_measurement:e.config?.currency||"EUR"}function ye(e,t,i){return`radial-gradient(ellipse 70% 60% at 50% 25%, ${t}${Math.round(.06*255).toString(16).padStart(2,"0")} 0%, transparent 100%),\n            radial-gradient(circle at 2px 2px, ${e.dotColor} 0.7px, transparent 0.7px)`}function ve(e,t){if(!e?.states)return"";const i=t||"sensor.sem_";return["pv1","pv2","pv3","pv4"].map(t=>e.states[`${i}pv_string_${t}_power`]?.state??"").join("|")}function xe(e,t){if(!e||!e.states)return[];const i=t||"sensor.sem_",s=[];for(const t of["pv1","pv2","pv3","pv4"]){const r=`${i}pv_string_${t}_power`,a=e.states[r];if(!a)continue;const o=parseFloat(a.state);if(isNaN(o))continue;const n=`${i}pv_string_${t}_daily_energy`,l=e.states[n],c=l?parseFloat(l.state):NaN;s.push({slot:t,watts:o,entityId:r,energyKwh:isNaN(c)?null:c,energyEntityId:l?n:null,name:a.attributes&&a.attributes.string_name||"PV"+t.replace(/^pv/,"")})}return s.length>=2?s:[]}const be="\n    .pv-strings-row {\n        display: flex;\n        flex-wrap: wrap;\n        gap: 6px;\n        padding: 6px 12px;\n        font-family: 'Segoe UI','Roboto',sans-serif;\n        font-size: 12px;\n    }\n    .pv-chip {\n        display: inline-flex;\n        align-items: baseline;\n        gap: 4px;\n        padding: 2px 8px;\n        background: rgba(255, 152, 0, 0.10);\n        border: 1px solid rgba(255, 152, 0, 0.25);\n        border-radius: 999px;\n        color: var(--secondary-text-color, #aaa);\n        cursor: pointer;\n        transition: background 120ms ease;\n    }\n    .pv-chip:hover { background: rgba(255, 152, 0, 0.18); }\n    .pv-chip-label {\n        font-size: 11px;\n        letter-spacing: 0.5px;\n        text-transform: uppercase;\n        opacity: 0.7;\n    }\n    .pv-chip-value {\n        color: var(--sem-solar, #ff9800);\n        font-weight: 600;\n        font-variant-numeric: tabular-nums;\n    }\n";function $e(e,t,i){customElements.get(e)||(customElements.define(e,t),i&&(window.customCards=window.customCards||[],window.customCards.push(i)))}const we=a`
    ha-card {
        background-color: var(--card-background-color);
        color: var(--primary-text-color);
        border: 1px solid var(--divider-color);
        border-radius: 16px;
        box-shadow: var(--ha-card-box-shadow, 0 2px 8px rgba(0, 0, 0, 0.08));
        max-width: 900px;
        font-family: 'Segoe UI', 'Roboto', sans-serif;
        transition: box-shadow 0.3s cubic-bezier(0.4, 0, 0.2, 1),
                    border-color 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        --chip-background: var(--secondary-background-color);
        --primary-font-family: 'Segoe UI', 'Roboto', sans-serif;
    }
    ha-card:hover {
        box-shadow: var(--ha-card-box-shadow, 0 4px 16px rgba(0, 0, 0, 0.12));
    }
`;class ke extends ce{constructor(){super(),this._hass=null,this._config=null,this._lang=null,this._localizeReady=!1,this._prevVals={},this._frozenEntities={},this._holdTimers={},this._holdIntervals={},this._cachedTheme=null,this._updateTimer=null}set hass(e){this._hass,this._hass=e;const t=e?.language,i="function"==typeof semLocalize;let s=!1;if((t!==this._lang||i&&!this._localizeReady)&&(this._lang=t,this._localizeReady=i,s=!0),this._isFrozen()&&!s)return;const r=this.constructor.watchedEntities||[];if(r.length>0&&!s){const t=e.states[r[0]]?.state;if("unavailable"===t||"unknown"===t)return}let a=!1;for(const t of r){const i=e.states[t]?.state;if(this._prevVals[t]!==i){a=!0;break}}if(a||s){for(const t of r)this._prevVals[t]=e.states[t]?.state;this._scheduleUpdate()}}get hass(){return this._hass}_scheduleUpdate(){this._updateTimer||(this._updateTimer=setTimeout(()=>{this._updateTimer=null,this.requestUpdate()},16))}_theme(){const e=getComputedStyle(document.documentElement).getPropertyValue("--primary-background-color").trim();return this._cachedTheme&&this._cachedThemeKey===e||(this._cachedThemeKey=e,this._cachedTheme=function(){const e=document.documentElement,t=getComputedStyle(e),i=(e,i)=>t.getPropertyValue(e).trim()||i,s=i("--primary-text-color","#e0e0e0"),r=i("--secondary-text-color","#888888"),a=i("--card-background-color","rgba(30,35,45,0.5)"),o=i("--divider-color","rgba(255,255,255,0.12)"),n=i("--secondary-background-color","rgba(255,255,255,0.06)"),l=i("--ha-card-box-shadow","0 2px 8px rgba(0,0,0,0.15)"),c=i("--primary-color","#42a5f5"),d=(()=>{const e=i("--primary-background-color","#111"),t=e.match(/\d+/g);return t&&t.length>=3?(.299*+t[0]+.587*+t[1]+.114*+t[2])/255<.5:!(e.startsWith("#f")||e.startsWith("#e")||e.startsWith("#d")||e.startsWith("#c")||e.startsWith("rgb(2"))})();return{text:s,textSec:r,cardBg:a,divider:o,bgSec:n,shadow:l,accent:c,isDark:d,textTertiary:d?"rgba(255,255,255,0.45)":"rgba(0,0,0,0.50)",textDisabled:d?"rgba(255,255,255,0.26)":"rgba(0,0,0,0.30)",surface:d?"rgba(255,255,255,0.06)":"rgba(0,0,0,0.03)",surfaceHover:d?"rgba(255,255,255,0.10)":"rgba(0,0,0,0.06)",surfaceBorder:d?"rgba(255,255,255,0.12)":"rgba(0,0,0,0.08)",dotColor:d?"rgba(128,128,128,0.05)":"rgba(128,128,128,0.06)",glowAlpha:d?.05:.03,tooltipBg:d?"rgba(20,20,30,0.95)":"rgba(255,255,255,0.95)",tooltipText:d?"#e0e0e0":"#333333",tooltipBorder:d?"rgba(255,255,255,0.15)":"rgba(0,0,0,0.12)"}}()),this._cachedTheme}_t(e){return e?"function"==typeof semLocalize?semLocalize(e,this._hass?.language):e:""}_forecastProviderLabel(e){if(!e)return"";return{solcast:"Solcast",forecast_solar:"Forecast.Solar",custom:this._t("custom")||"Custom"}[e]||e}_state(e,t=0){const i=this._frozenEntities[e];if(i)return i.value;const s=this._hass?.states[e];return s&&"unavailable"!==s.state&&"unknown"!==s.state?parseFloat(s.state)??t:t}_stateStr(e){const t=this._frozenEntities[e];if(t)return String(t.value);const i=this._hass?.states[e];return i&&"unavailable"!==i.state&&"unknown"!==i.state?i.state:""}_pcEntity(e,t,i){const s=this._hass?.states||{},r=new RegExp(`^${e}\\.sem_charger_.+_${t}$`);let a=Object.keys(s).filter(e=>r.test(e));return"night_charging"===t&&(a=a.filter(e=>!e.endsWith("_smart_night_charging"))),a.sort(),a.length?a[0]:i}_stateAttrs(e){return this._hass?.states[e]?.attributes||{}}_freezeEntity(e,t){const i=this._frozenEntities[e];i?.timer&&clearTimeout(i.timer),this._frozenEntities[e]={value:t,timer:setTimeout(()=>{delete this._frozenEntities[e],this.requestUpdate()},1500)}}_isFrozen(){return Object.keys(this._frozenEntities).length>0}async _callService(e,t,i){if(this._hass)try{await this._hass.callService(e,t,i)}catch(e){console.error(`[SEM ${this.tagName}]`,e)}}_setNumber(e,t){const i=this._hass?.states[e];if(!i)return;const s=parseFloat(i.attributes.min)||0,r=parseFloat(i.attributes.max)||100,a=Math.max(s,Math.min(r,t));this._freezeEntity(e,a),this.requestUpdate(),this._callService("number","set_value",{entity_id:e,value:a})}_stepNumber(e,t){const i=this._hass?.states[e];if(!i)return;const s=this._frozenEntities[e],r=s?s.value:parseFloat(i.state)||0,a=parseFloat(i.attributes.step)||1;this._setNumber(e,r+t*a)}_toggleSwitch(e){const t=this._hass?.states[e];if(!t)return;const i="on"===t.state?"off":"on";this._freezeEntity(e,i),this.requestUpdate();const s="on"===t.state?"turn_off":"turn_on";this._callService("switch",s,{entity_id:e})}_selectOption(e,t){this._freezeEntity(e,t),this.requestUpdate(),this._callService("select","select_option",{entity_id:e,option:t})}_startHold(e,t){this._stopHold(e),this._holdTimers[e]=setTimeout(()=>{this._holdIntervals[e]=setInterval(()=>{this._stepNumber(e,t)},150)},400)}_stopHold(e){clearTimeout(this._holdTimers[e]),clearInterval(this._holdIntervals[e]),delete this._holdTimers[e],delete this._holdIntervals[e]}updated(){if(window._semDebug){this.style.outline="2px solid red",this.style.outlineOffset="-2px",clearTimeout(this._debugFlashTimer),this._debugFlashTimer=setTimeout(()=>{this.style.outline="",this.style.outlineOffset=""},200);const e=this.tagName.toLowerCase();window._semRenderLog||(window._semRenderLog={}),window._semRenderLog[e]=(window._semRenderLog[e]||0)+1}}connectedCallback(){super.connectedCallback(),window._semDebug&&console.log(`[SEM DEBUG] ${this.tagName} connectedCallback`),this._localizeReady||"function"==typeof semLocalize?"function"==typeof semLocalize&&(this._localizeReady=!0):(this._onLocalizeReady=()=>{document.removeEventListener("sem-localize-ready",this._onLocalizeReady),this._onLocalizeReady=null,this._localizeReady=!0,this._hass&&this.requestUpdate()},document.addEventListener("sem-localize-ready",this._onLocalizeReady))}disconnectedCallback(){super.disconnectedCallback(),window._semDebug&&console.log(`[SEM DEBUG] ${this.tagName} disconnectedCallback !!!`),this._onLocalizeReady&&(document.removeEventListener("sem-localize-ready",this._onLocalizeReady),this._onLocalizeReady=null),this._updateTimer&&(clearTimeout(this._updateTimer),this._updateTimer=null);for(const e of Object.keys(this._holdTimers))this._stopHold(e);for(const e of Object.keys(this._frozenEntities))clearTimeout(this._frozenEntities[e]?.timer);this._frozenEntities={}}setConfig(e){this._config=e}getCardSize(){return 4}static getStubConfig(){return{}}}$e("sem-title-card",class extends ke{static get watchedEntities(){return[]}constructor(){super(),this._renderedSubtitle=null,this._templateUnsub=null,this._templateSubbed=!1}setConfig(e){super.setConfig(e),this._unsubTemplate(),this._templateSubbed=!1,this._renderedSubtitle=null}_hasJinja(e){return e&&(e.includes("{%")||e.includes("{{"))}set hass(e){this._hass,this._hass=e;const t=e?.language,i="function"==typeof semLocalize;(t!==this._lang||i&&!this._localizeReady)&&(this._lang=t,this._localizeReady=i,this.requestUpdate()),this._hasJinja(this._config?.subtitle)&&!this._templateSubbed&&this._subscribeTemplate()}_subscribeTemplate(){if(!this._hass?.connection||this._templateSubbed)return;this._templateSubbed=!0;const e=this._config.subtitle;this._hass.connection.subscribeMessage(e=>{const t=e.result;t!==this._renderedSubtitle&&(this._renderedSubtitle=t,this.requestUpdate())},{type:"render_template",template:e,variables:{}}).then(e=>{this._templateUnsub=e}).catch(()=>{this._renderedSubtitle=this._config.subtitle,this.requestUpdate()})}_unsubTemplate(){this._templateUnsub&&(this._templateUnsub(),this._templateUnsub=null)}disconnectedCallback(){super.disconnectedCallback(),this._unsubTemplate()}render(){if(!this._config)return q;const e=this._t(this._config.title_key||this._config.title||"");let t="";t=this._hasJinja(this._config.subtitle)?this._renderedSubtitle||"":this._t(this._config.subtitle||"");const i=this._theme();return W`
            <style>
                :host { display: block; }
                .sem-title-wrap {
                    padding: 8px 0 0 0;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                }
                .title {
                    font-size: 16px;
                    font-weight: 600;
                    letter-spacing: 0.5px;
                    color: ${i.text};
                    line-height: 1.3;
                    padding: 0 16px;
                }
                .subtitle {
                    font-size: 12px;
                    color: ${i.textSec};
                    margin-top: 2px;
                    line-height: 1.4;
                    padding: 0 16px;
                }
                .divider {
                    height: 1px;
                    margin: 4px 16px 0;
                    background: linear-gradient(90deg, rgba(150,202,238,0.25) 0%, transparent 70%);
                }
            </style>
            <div class="sem-title-wrap">
                <div class="title">${e}</div>
                ${t?W`<div class="subtitle">${t}</div>`:q}
                <div class="divider"></div>
            </div>
        `}getCardSize(){return 1}static getStubConfig(){return{title:"Section Title"}}},{type:"sem-title-card",name:"SEM Title Card",description:"Runtime-translated section header for SEM dashboard"});class Se extends ke{static properties={...ke.properties,_available:{state:!0}};setConfig(e){if(!e?.requires||!e?.card)throw new Error('sem-require: "requires" and "card" are mandatory');this._config=e,this._available=!!customElements.get(e.requires),this._inner=null,this._available||customElements.whenDefined(e.requires).then(()=>{this._available=!0,this._inner=null,this.requestUpdate()})}set hass(e){this._hass=e,this._inner&&(this._inner.hass=e),this.requestUpdate()}async _buildInner(){if(this._inner||!this._available)return;const e=await window.loadCardHelpers();this._inner=e.createCardElement(this._config.card),this._hass&&(this._inner.hass=this._hass),this.requestUpdate()}render(){if(!this._config)return q;if(this._available)return this._inner?W`${this._inner}`:(this._buildInner(),q);const e=this._config.name||this._config.requires;return W`
            <ha-card>
                <div class="notice">
                    <ha-icon icon="mdi:puzzle-outline"></ha-icon>
                    <div class="text">
                        <div class="title">${this._t("require_missing_title").replace("{name}",e)}</div>
                        <div class="body">${this._t("require_missing_body").replace("{name}",e)}</div>
                    </div>
                </div>
            </ha-card>
        `}static styles=a`
        .notice {
            display: flex; gap: 14px; align-items: center;
            padding: 16px;
        }
        .notice ha-icon { --mdc-icon-size: 30px; color: var(--warning-color, #ffa726); }
        .title { font-weight: 600; margin-bottom: 4px; }
        .body { font-size: 13px; opacity: 0.85; line-height: 1.4; }
    `;getCardSize(){return this._inner?.getCardSize?.()||3}}$e("sem-require",Se,{type:"custom:sem-require",name:"SEM Require Wrapper",description:"Renders a card only when its HACS dependency is installed; otherwise a friendly install notice",preview:!1});const Ce=(e,t)=>"function"==typeof semLocalize?semLocalize(e,t?.language):e,ze={home:{titleKey:"home",subtitleKey:"home_sub",color:"#5BC8D8",icon:()=>j`
            <path d="M-20,2 L0,-16 L20,2" stroke-width="2"/>
            <rect x="-15" y="2" width="30" height="22" rx="2" stroke-width="2"/>
            <rect x="-5" y="12" width="10" height="12" stroke-width="1.5"/>`},energy:{titleKey:"energy",subtitleKey:"energy_sub",color:"#ff9800",icon:()=>j`
            <path d="M-4,-18 L-10,2 L-2,2 L-6,18 L12,-4 L2,-4 L8,-18 Z" stroke-width="2"/>`},battery:{titleKey:"battery",subtitleKey:"battery_sub",color:"#4db6ac",icon:()=>j`
            <rect x="-10" y="-16" width="20" height="32" rx="4" stroke-width="2"/>
            <rect x="-4" y="-20" width="8" height="5" rx="2" fill="currentColor" opacity="0.4" stroke="none"/>
            <line x1="-5" y1="-4" x2="5" y2="-4" stroke-width="1.5" opacity="0.5"/>
            <line x1="-5" y1="4" x2="5" y2="4" stroke-width="1.5" opacity="0.5"/>`},ev:{titleKey:"ev_charging",subtitleKey:"ev_sub",color:"#8DC892",icon:()=>j`
            <rect x="-12" y="-14" width="24" height="24" rx="5" stroke-width="2"/>
            <path d="M-3,-6 L-1,0 L-5,0 L3,8" stroke-width="2" fill="none"/>
            <line x1="0" y1="10" x2="0" y2="16" stroke-width="2"/>
            <circle cx="0" cy="18" r="2" fill="currentColor" opacity="0.4" stroke="none"/>`},control:{titleKey:"control",subtitleKey:"control_sub",color:"#96CAEE",icon:()=>j`
            <line x1="-12" y1="-12" x2="-12" y2="12" stroke-width="2"/>
            <line x1="0" y1="-12" x2="0" y2="12" stroke-width="2"/>
            <line x1="12" y1="-12" x2="12" y2="12" stroke-width="2"/>
            <circle cx="-12" cy="-4" r="4" fill="currentColor" opacity="0.6" stroke="none"/>
            <circle cx="0" cy="4" r="4" fill="currentColor" opacity="0.6" stroke="none"/>
            <circle cx="12" cy="-8" r="4" fill="currentColor" opacity="0.6" stroke="none"/>`},config:{titleKey:"config_tab_title",subtitleKey:"config_tab_subtitle",color:"#8DC892",icon:()=>j`
            <circle cx="0" cy="0" r="6" stroke-width="2"/>
            <g stroke-width="2" stroke-linecap="round">
                <line x1="0" y1="-16" x2="0" y2="-10"/>
                <line x1="0" y1="10" x2="0" y2="16"/>
                <line x1="-16" y1="0" x2="-10" y2="0"/>
                <line x1="10" y1="0" x2="16" y2="0"/>
                <line x1="-11" y1="-11" x2="-7" y2="-7"/>
                <line x1="7" y1="7" x2="11" y2="11"/>
                <line x1="11" y1="-11" x2="7" y2="-7"/>
                <line x1="-7" y1="7" x2="-11" y2="11"/>
            </g>`},costs:{titleKey:"costs",subtitleKey:"costs_sub",color:"#f06292",icon:()=>j`
            <circle cx="0" cy="0" r="16" stroke-width="2"/>
            <text x="0" y="6" text-anchor="middle" font-size="18" font-weight="700"
                  fill="currentColor" opacity="0.7" stroke="none"
                  font-family="'Segoe UI','Roboto',sans-serif">$</text>`},system:{titleKey:"system",subtitleKey:"system_sub",color:"#96CAEE",icon:()=>j`
            <path d="M-16,4 L-8,-8 L0,0 L6,-12 L10,-4 L16,4" stroke-width="2" fill="none"/>
            <line x1="-16" y1="8" x2="16" y2="8" stroke-width="1" opacity="0.3"/>`}};$e("sem-tab-header",class extends ke{static get watchedEntities(){return[]}constructor(){super(),this._tab="home",this._prefix="sensor.sem_",this._responsiveApplied=!1,this._lastStatsKey=""}connectedCallback(){super.connectedCallback(),this._applyResponsiveContainer()}_applyResponsiveContainer(){this._responsiveApplied||requestAnimationFrame(()=>{let e=this;for(;e;){const t=e.getRootNode()?.host;if(!t)break;if("HUI-VERTICAL-STACK-CARD"===t.tagName){const e=t.parentElement;if(e&&"HUI-CARD"===e.tagName)return e.style.maxWidth="900px",e.style.margin="0 auto",e.style.display="block",void(this._responsiveApplied=!0)}e=t}})}setConfig(e){super.setConfig(e),this._tab=e.tab||"home",this._prefix=e.entity_prefix||"sensor.sem_"}set hass(e){this._hass,this._hass=e;const t=e?.language,i="function"==typeof semLocalize;let s=!1;if((t!==this._lang||i&&!this._localizeReady)&&(this._lang=t,this._localizeReady=i,s=!0),this._isFrozen()&&!s)return;const r=this._buildStatsKey(e);(r!==this._lastStatsKey||s)&&(this._lastStatsKey=r,this.requestUpdate()),this._responsiveApplied||this._applyResponsiveContainer()}_buildStatsKey(e){if(!e)return"";const t=t=>e.states[`${this._prefix}${t}`]?.state||"",i=this._tab;return"home"===i?[t("solar_power"),t("daily_solar_energy")].join(","):"energy"===i?[t("daily_solar_energy"),t("daily_home_energy"),t("self_consumption_rate")].join(","):"battery"===i?[t("battery_soc"),t("battery_power"),t("battery_health_score")].join(","):"ev"===i?[t("ev_power"),t("daily_ev_energy"),t("charging_state")].join(","):"control"===i?[t("target_peak_limit"),t("controllable_devices_count"),t("surplus_active_devices")].join(","):"config"===i?[t("charging_state"),t("heat_pump_registered"),t("battery_status")].join(","):"costs"===i?[t("daily_costs"),t("daily_savings"),t("daily_net_cost")].join(","):"system"===i?[t("energy_optimization_score"),t("lifetime_total_savings"),t("lifetime_co2_avoided")].join(","):""}_getState(e,t=0){const i=this._hass?.states[`${this._prefix}${e}`];return i&&"unavailable"!==i.state&&"unknown"!==i.state?parseFloat(i.state)??t:t}_getStatLabels(){const e=e=>Ce(e,this._hass),t=this._tab;return"home"===t?[e("solar"),e("autarky"),e("self_use"),e("today")]:"energy"===t?[e("solar"),e("home"),e("self_use")]:"battery"===t?[e("soc"),e("power"),e("health")]:"ev"===t?[e("power"),e("today"),e("session")]:"control"===t?[e("peak"),e("devices"),e("active")]:"config"===t?[e("config_stat_chargers"),e("config_stat_heatpump"),e("config_stat_battery")]:"costs"===t?[e("cost"),e("saved"),e("net")]:"system"===t?[e("score"),e("saved"),e("co2")]:["—","—","—"]}_getStatValues(){const e=this._tab,t=me(this._hass)||"EUR";if("home"===e)return[ge(this._getState("solar_power",0)),this._getState("autarky_rate",0).toFixed(0)+"%",this._getState("self_consumption_rate",0).toFixed(0)+"%",this._getState("daily_solar_energy",0).toFixed(1)+" kWh"];if("energy"===e)return[this._getState("daily_solar_energy",0).toFixed(1)+" kWh",this._getState("daily_home_energy",0).toFixed(1)+" kWh",this._getState("self_consumption_rate",0).toFixed(0)+"%"];if("battery"===e)return[this._getState("battery_soc",0).toFixed(0)+"%",ge(this._getState("battery_power",0)),this._getState("battery_health_score",100).toFixed(0)+"%"];if("ev"===e)return[ge(this._getState("ev_power",0)),this._getState("daily_ev_energy",0).toFixed(1)+" kWh",this._getState("session_energy",0).toFixed(1)+" kWh"];if("control"===e)return[this._getState("target_peak_limit",5).toFixed(1)+" kW",this._getState("controllable_devices_count",0).toFixed(0),this._getState("surplus_active_devices",0).toFixed(0)];if("config"===e){const e=e=>Ce(e,this._hass),t=Object.keys(this._hass?.states||{}).filter(e=>e.match(/^number\.sem_charger_.+_minimum_current$/)).length,i="on"===this._hass?.states[`${this._prefix}heat_pump_registered`]?.state,s=this._hass?.states[`${this._prefix}battery_soc`];return[String(t),e(i?"on":"off"),s?Math.round(parseFloat(s.state)||0)+"%":"—"]}return"costs"===e?[this._getState("daily_costs",0).toFixed(2)+" "+t,this._getState("daily_savings",0).toFixed(2)+" "+t,(()=>{const e=this._getState("daily_net_cost",0);return(e<=0?"+":"")+Math.abs(e).toFixed(2)+" "+t})()]:"system"===e?[this._getState("energy_optimization_score",0).toFixed(0),this._getState("lifetime_total_savings",0).toFixed(0)+" "+t,this._getState("lifetime_co2_avoided",0).toFixed(0)+" kg"]:["—","—","—"]}_renderHomeHero(){const e=this._getState("daily_solar_energy",0),t=this._getState("solar_power",0);return W`
            <div class="hero">
                <div class="hero-main">
                    <div class="hero-value">${e.toFixed(1)}<span class="unit">kWh</span></div>
                    <div class="hero-label">${Ce("todays_solar_production",this._hass)}</div>
                </div>
                ${t>0?W`
                <div class="hero-now">
                    <ha-icon icon="mdi:white-balance-sunny"></ha-icon>
                    <span>${ge(t)}</span>
                </div>`:q}
            </div>`}render(){if(!this._hass||!this._config)return q;const e=ze[this._tab]||ze.home,t=this._config.title||Ce(e.titleKey,this._hass),i=this._config.subtitle||Ce(e.subtitleKey,this._hass),s=e.color,r=this._getStatLabels(),a=this._getStatValues(),o=this._theme(),n=o.isDark?s:`color-mix(in srgb, ${s} 65%, black)`,l=o.isDark?`0 0 12px ${s}40`:"none",c=o.isDark?.3:.18;return W`
            <style>
                :host { display: block; }
                .header-wrap {
                    display: flex; align-items: center; gap: 16px;
                    padding: 16px 20px; position: relative; overflow: hidden;
                    background:
                        radial-gradient(ellipse 80% 70% at 20% 50%, ${s}0D 0%, transparent 70%),
                        radial-gradient(circle at 2px 2px, ${o.dotColor} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                }
                .icon-ring { position: relative; flex-shrink: 0; width: 64px; height: 64px; }
                .icon-ring svg { width: 100%; height: 100%; }
                /* min-width keeps the title readable next to the stats;
                   when there isn't room for both, the stats wrap below
                   instead of crushing the title to zero width. */
                .title-area { flex: 1 1 auto; min-width: 140px; }
                .tab-title {
                    font-size: 20px; font-weight: 700; color: ${n};
                    letter-spacing: 0.5px; text-shadow: ${l};
                    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
                }
                .tab-subtitle {
                    font-size: 12px; color: var(--secondary-text-color, ${o.textSec});
                    margin-top: 2px; font-weight: 500;
                    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
                }
                .stats { display: flex; gap: 16px; flex-shrink: 0; }
                .stat { text-align: center; min-width: 50px; }
                .stat-value {
                    font-size: 15px; font-weight: 700; font-variant-numeric: tabular-nums;
                    color: var(--primary-text-color, ${o.text});
                }
                .stat-label {
                    font-size: 11px; color: var(--secondary-text-color, ${o.textTertiary});
                    font-weight: 500; margin-top: 1px;
                }
                /* Home hero — Today's production merged from the KPI card
                   (maintainer UI review: chips duplicated the KPI below) */
                .hero { display: flex; align-items: center; gap: 14px; flex-shrink: 0; }
                .hero-main { text-align: left; }
                .hero-value {
                    font-size: 26px; font-weight: 700; line-height: 1.05;
                    color: #ff9800; letter-spacing: -0.5px;
                    font-variant-numeric: tabular-nums; white-space: nowrap;
                }
                .hero-value .unit { font-size: 14px; font-weight: 500; opacity: 0.85; margin-left: 3px; }
                .hero-label {
                    font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px;
                    color: var(--secondary-text-color, ${o.textTertiary});
                    margin-top: 2px;
                }
                .hero-now {
                    display: flex; align-items: center; gap: 5px;
                    padding: 5px 10px; border-radius: 999px;
                    background: var(--secondary-background-color, rgba(255,255,255,0.06));
                    font-size: 12px; color: var(--primary-text-color, ${o.text});
                    white-space: nowrap;
                }
                .hero-now ha-icon { color: #ff9800; --mdc-icon-size: 14px; }
                @media (max-width: 500px) {
                    .hero-value { font-size: 21px; }
                }
                @media (max-width: 500px) {
                    .header-wrap { padding: 12px 14px; gap: 8px 12px; flex-wrap: wrap; }
                    .icon-ring { width: 48px; height: 48px; }
                    .tab-title { font-size: 16px; }
                    .stats { gap: 10px; }
                    .stat-value { font-size: 13px; }
                }
            </style>
            <ha-card>
                <div class="header-wrap">
                    <div class="icon-ring">
                        <svg viewBox="-34 -34 68 68" xmlns="http://www.w3.org/2000/svg">
                            <defs>
                                <filter id="glow-${this._tab}" x="-40%" y="-40%" width="180%" height="180%">
                                    <feGaussianBlur stdDeviation="4" result="blur"/>
                                    <feFlood flood-color="${s}" flood-opacity="${c}"/>
                                    <feComposite in2="blur" operator="in"/>
                                    <feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge>
                                </filter>
                            </defs>
                            <circle r="28" fill="none" stroke="${s}" stroke-width="1.2" opacity="0.25">
                                <animate attributeName="r" values="28;31;28" dur="3s" repeatCount="indefinite"/>
                                <animate attributeName="opacity" values="0.25;0.10;0.25" dur="3s" repeatCount="indefinite"/>
                            </circle>
                            <circle r="24" fill="${s}0F" stroke="${s}" stroke-width="1.5" filter="url(#glow-${this._tab})"/>
                            <g stroke="${s}" fill="none" opacity="0.75" stroke-linecap="round" stroke-linejoin="round">
                                ${e.icon()}
                            </g>
                        </svg>
                    </div>
                    <div class="title-area">
                        <div class="tab-title">${t}</div>
                        <div class="tab-subtitle">${i}</div>
                    </div>
                    ${"home"===this._tab?this._renderHomeHero():W`
                    <div class="stats">
                        ${r.map((e,t)=>W`
                            <div class="stat">
                                <div class="stat-value">${a[t]}</div>
                                <div class="stat-label">${e}</div>
                            </div>
                        `)}
                    </div>`}
                </div>
            </ha-card>
        `}getCardSize(){return 1}static getStubConfig(){return{tab:"home"}}},{type:"sem-tab-header",name:"SEM Tab Header",description:"Lumina-styled tab header with glow icon and live stats"});const Me={"clear-night":{icon:"🌙",key:"weather_clear"},cloudy:{icon:"☁️",key:"weather_cloudy"},fog:{icon:"🌫️",key:"weather_fog"},hail:{icon:"🧊",key:"weather_hail"},lightning:{icon:"⚡",key:"weather_thunder"},"lightning-rainy":{icon:"⛈️",key:"weather_thunderstorm"},partlycloudy:{icon:"⛅",key:"weather_partly_cloudy"},pouring:{icon:"🌧️",key:"weather_pouring"},rainy:{icon:"🌦️",key:"weather_rain"},snowy:{icon:"❄️",key:"weather_snow"},"snowy-rainy":{icon:"🌨️",key:"weather_sleet"},sunny:{icon:"☀️",key:"weather_sunny"},windy:{icon:"💨",key:"weather_windy"},"windy-variant":{icon:"💨",key:"weather_windy"},exceptional:{icon:"⚠️",key:"weather_exceptional"}};$e("sem-weather-card",class extends ke{static get styles(){return[we]}constructor(){super(),this._clockTime="--:--",this._clockDate="",this._clockInterval=null}static get watchedEntities(){return[]}setConfig(e){if(!e.entity)throw new Error("sem-weather-card requires entity");super.setConfig(e)}set hass(e){this._hass,this._hass=e;const t=e?.language,i="function"==typeof semLocalize;let s=!1;if((t!==this._lang||i&&!this._localizeReady)&&(this._lang=t,this._localizeReady=i,s=!0),this._isFrozen()&&!s)return;const r=this._config?.entity;if(!r)return;const a=e?.states[r],o=(a?.state||"")+JSON.stringify(a?.attributes?.forecast?.[0]||"")+"|"+(t||"");(o!==this._lastWeatherKey||s)&&(this._lastWeatherKey=o,this.requestUpdate())}get hass(){return this._hass}connectedCallback(){super.connectedCallback(),this._updateClock(),this._clockInterval=setInterval(()=>{this._updateClock()},3e4)}disconnectedCallback(){super.disconnectedCallback(),this._clockInterval&&(clearInterval(this._clockInterval),this._clockInterval=null)}_updateClock(){const e=new Date,t=this._hass?.language||navigator.language||"en",i=this._hass?.config?.time_zone||void 0;this._clockTime=e.toLocaleTimeString(t,{hour:"2-digit",minute:"2-digit",timeZone:i}),this._clockDate=e.toLocaleDateString(t,{weekday:"long",day:"numeric",month:"long",year:"numeric",timeZone:i}),this.requestUpdate()}_renderForecastRows(e,t){const i=this._hass?.language||navigator.language||"en",s=this._hass?.config?.time_zone||void 0;return e.slice(0,t).map(e=>{const t=new Date(e.datetime).toLocaleDateString(i,{weekday:"short",timeZone:s}),r=Me[e.condition]?.icon||"❓",a=null!=e.templow?Math.round(e.templow):"—",o=null!=e.temperature?Math.round(e.temperature):"—",n="number"==typeof o&&"number"==typeof a?o-a:0,l=Math.max(n/30*100,10),c="number"==typeof o&&"number"==typeof a?(a+o)/2:15,d=Math.min(Math.max((c-0)/30,0),1),p=d>.5?`rgba(255,${Math.round(200-100*d)},0,0.6)`:`rgba(${Math.round(100+200*d)},${Math.round(180+40*d)},255,0.5)`;return W`
                <div class="forecast-row">
                    <span class="f-day">${t}</span>
                    <span class="f-icon">${r}</span>
                    <span class="f-low">${a}°</span>
                    <div class="f-bar-wrap">
                        <div class="f-bar" style="width:${l}%;background:${p}"></div>
                    </div>
                    <span class="f-high">${o}°</span>
                </div>
            `})}_findUsableWeatherEntity(){const e=this._hass?.states;if(!e)return null;const t=Object.keys(e).filter(t=>{if(!t.startsWith("weather."))return!1;const i=e[t];return i&&"unavailable"!==i.state&&"unknown"!==i.state&&i.attributes&&null!=i.attributes.temperature});return t.filter(e=>!e.startsWith("weather.forecast_"))[0]||t[0]||null}render(){if(!this._config)return q;let e=this._config.entity;const t=this._config.forecast_rows||5;let i=this._hass?.states[e];if(!i||"unavailable"===i.state||null==i.attributes?.temperature){const t=this._findUsableWeatherEntity();t&&(e=t,i=this._hass.states[t])}if(!i)return W`
                <ha-card>
                    <div style="padding:16px;color:#ef5350">Entity ${e} not found</div>
                </ha-card>
            `;const s=this._theme(),r=i.state,a=i.attributes,o=null!=a.temperature?Math.round(a.temperature):"—",n=a.temperature_unit||"°C",l=null!=a.humidity?Math.round(a.humidity):"—",c=null!=a.wind_speed?Math.round(a.wind_speed):"—",d=a.wind_speed_unit||"km/h",p=Me[r]||{icon:"❓",key:""},h=a.forecast||[];return W`
            <style>
                :host { display: block; }
                .wrap {
                    padding: 24px 20px 16px;
                    position: relative;
                    background:
                        radial-gradient(ellipse 70% 60% at 50% 35%, rgba(200,220,240,0.06) 0%, transparent 100%),
                        radial-gradient(circle at 2px 2px, ${s.dotColor} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${s.text});
                }
                .clock-section {
                    display: flex;
                    justify-content: space-between;
                    align-items: flex-start;
                    margin-bottom: 20px;
                }
                .clock-left { flex: 1; }
                .time {
                    font-size: 48px;
                    font-weight: 700;
                    font-variant-numeric: tabular-nums;
                    letter-spacing: -1px;
                    line-height: 1;
                    color: var(--primary-text-color, ${s.text});
                    text-shadow: 0 0 20px rgba(200,220,240,0.15);
                }
                .date {
                    font-size: 13px;
                    color: var(--secondary-text-color, ${s.textSec});
                    margin-top: 6px;
                    font-weight: 500;
                }
                .weather-current {
                    text-align: right;
                    flex-shrink: 0;
                }
                .weather-icon {
                    font-size: 40px;
                    line-height: 1;
                    filter: drop-shadow(0 0 8px rgba(200,220,240,0.2));
                }
                .weather-label {
                    font-size: 12px;
                    color: var(--secondary-text-color, ${s.textSec});
                    margin-top: 2px;
                    font-weight: 500;
                }
                .temp {
                    font-size: 28px;
                    font-weight: 700;
                    font-variant-numeric: tabular-nums;
                    color: var(--primary-text-color, ${s.text});
                    text-shadow: 0 0 12px rgba(200,220,240,0.1);
                }
                .weather-details {
                    display: flex;
                    gap: 16px;
                    margin-bottom: 16px;
                    padding-bottom: 14px;
                    border-bottom: 1px solid var(--divider-color, ${s.surfaceBorder});
                }
                .detail {
                    display: flex;
                    align-items: center;
                    gap: 6px;
                    font-size: 12px;
                    color: var(--secondary-text-color, ${s.textSec});
                }
                .detail-icon { font-size: 14px; opacity: 0.7; }
                .forecast-rows {
                    display: flex;
                    flex-direction: column;
                    gap: 6px;
                }
                .forecast-row {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    font-size: 13px;
                    font-variant-numeric: tabular-nums;
                    padding: 4px 0;
                }
                .f-day {
                    width: 32px;
                    color: var(--secondary-text-color, ${s.textSec});
                    font-weight: 500;
                    font-size: 12px;
                }
                .f-icon { font-size: 16px; width: 24px; text-align: center; }
                .f-low {
                    width: 30px;
                    text-align: right;
                    color: #78a8d8;
                    font-weight: 500;
                    font-size: 12px;
                }
                .f-bar-wrap {
                    flex: 1;
                    height: 4px;
                    background: var(--secondary-background-color, ${s.surface});
                    border-radius: 2px;
                    overflow: hidden;
                }
                .f-bar {
                    height: 100%;
                    border-radius: 2px;
                    transition: width 0.5s cubic-bezier(0.4,0,0.2,1);
                }
                .f-high {
                    width: 30px;
                    text-align: right;
                    color: #e0a050;
                    font-weight: 600;
                    font-size: 12px;
                }
            </style>
            <ha-card>
                <div class="wrap">
                    <div class="clock-section">
                        <div class="clock-left">
                            <div class="time">${this._clockTime}</div>
                            <div class="date">${this._clockDate}</div>
                        </div>
                        <div class="weather-current">
                            <div class="weather-icon">${p.icon}</div>
                            <div class="weather-label">${this._t(p.key)}</div>
                            <div class="temp">${o}${n}</div>
                        </div>
                    </div>

                    <div class="weather-details">
                        <div class="detail">
                            <span class="detail-icon">💧</span>
                            <span>${l}%</span>
                        </div>
                        <div class="detail">
                            <span class="detail-icon">💨</span>
                            <span>${c} ${d}</span>
                        </div>
                    </div>

                    <div class="forecast-rows">
                        ${h.length?this._renderForecastRows(h,t):q}
                    </div>
                </div>
            </ha-card>
        `}getCardSize(){return 5}static getStubConfig(){return{entity:"weather.home"}}},{type:"custom:sem-weather-card",name:"SEM Weather",description:"Lumina-styled clock + weather card with forecast",preview:!1});const Ee=[{key:"today",labelKey:"period_today"},{key:"yesterday",labelKey:"period_yesterday"},{key:"week",labelKey:"period_this_week"},{key:"month",labelKey:"period_this_month"},{key:"year",labelKey:"period_this_year"}];$e("sem-period-selector-card",class extends ke{static get styles(){return[we]}static get watchedEntities(){return[]}constructor(){super(),this._active="week",this._firstRender=!0}setConfig(e){super.setConfig(e),e.default_period&&(this._active=e.default_period)}set hass(e){this._hass,this._hass=e;const t=e?.language,i="function"==typeof semLocalize;(t!==this._lang||i&&!this._localizeReady)&&(this._lang=t,this._localizeReady=i,this.requestUpdate())}get hass(){return this._hass}firstUpdated(){this._dispatchPeriod(this._active)}_getPeriod(e){const t=new Date,i=(e=>new Date(e.getFullYear(),e.getMonth(),e.getDate()))(t);switch(e){case"today":return{start:i,end:t,granularity:"hour"};case"yesterday":{const e=new Date(i);return e.setDate(e.getDate()-1),{start:e,end:i,granularity:"hour"}}case"week":{const e=t.getDay()||7,s=new Date(i);return s.setDate(s.getDate()-(e-1)),{start:s,end:t,granularity:"day"}}case"month":return{start:new Date(t.getFullYear(),t.getMonth(),1),end:t,granularity:"day"};case"year":return{start:new Date(t.getFullYear(),0,1),end:t,granularity:"month"};default:return this._getPeriod("week")}}_dispatchPeriod(e){this._active=e,this.requestUpdate();const t=this._getPeriod(e);document.dispatchEvent(new CustomEvent("sem-period-change",{detail:{...t,key:e}}))}render(){if(!this._config)return q;const e=this._theme();return W`
            <style>
                :host { display: block; }
                .sem-period {
                    display: flex;
                    gap: 8px;
                    padding: 12px 16px;
                    justify-content: center;
                    flex-wrap: wrap;
                    background:
                        radial-gradient(ellipse 80% 60% at 50% 50%, rgba(200,220,240,0.04) 0%, transparent 100%),
                        radial-gradient(circle at 2px 2px, ${e.dotColor} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                }
                .btn {
                    border: 1px solid var(--divider-color, ${e.surfaceBorder});
                    background: var(--secondary-background-color, ${e.surface});
                    color: var(--secondary-text-color, ${e.textSec});
                    padding: 8px 18px;
                    border-radius: 12px;
                    font-size: 13px;
                    font-weight: 500;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    font-variant-numeric: tabular-nums;
                    cursor: pointer;
                    transition: all 0.3s cubic-bezier(0.4,0,0.2,1);
                    backdrop-filter: blur(8px);
                    -webkit-backdrop-filter: blur(8px);
                    user-select: none;
                }
                .btn:hover {
                    background: var(--secondary-background-color, ${e.surfaceHover});
                    color: var(--primary-text-color, ${e.text});
                    border-color: var(--divider-color, ${e.surfaceBorder});
                }
                .btn.active {
                    background: rgba(66,165,245,0.18);
                    border-color: rgba(66,165,245,0.40);
                    color: ${e.accent};
                    box-shadow: 0 0 16px rgba(66,165,245,0.12), 0 0 4px rgba(66,165,245,0.08);
                    font-weight: 600;
                }
            </style>
            <ha-card>
                <div class="sem-period">
                    ${Ee.map(e=>W`
                        <button
                            class="btn ${this._active===e.key?"active":""}"
                            role="button"
                            aria-label=${this._t(e.labelKey)}
                            aria-pressed=${this._active===e.key}
                            @click=${()=>this._dispatchPeriod(e.key)}
                        >${this._t(e.labelKey)}</button>
                    `)}
                </div>
            </ha-card>
        `}getCardSize(){return 1}static getStubConfig(){return{}}},{type:"custom:sem-period-selector-card",name:"SEM Period Selector",description:"Glassmorphism period picker for SEM chart cards",preview:!1});const De="sensor.sem_",Fe=["flow_solar_to_home_energy","flow_solar_to_ev_energy","daily_co2_avoided","yearly_co2_avoided","lifetime_co2_avoided","yearly_trees_equivalent","lifetime_trees_equivalent"];function Ie(e){return Fe.map(t=>`${e}${t}`)}$e("sem-energy-impact-card",class extends ke{static get watchedEntities(){return Ie(De)}setConfig(e){super.setConfig(e),this._prefix=e.entity_prefix||De,this._prefix!==De&&(this._prevVals={})}set hass(e){this._hass,this._hass=e;const t=e?.language,i="function"==typeof semLocalize;let s=!1;if((t!==this._lang||i&&!this._localizeReady)&&(this._lang=t,this._localizeReady=i,s=!0),this._isFrozen()&&!s)return;const r=Ie(this._prefix||De);let a=!1;for(const t of r)if(this._prevVals[t]!==e.states[t]?.state){a=!0;break}if(a||s){for(const t of r)this._prevVals[t]=e.states[t]?.state;this._scheduleUpdate()}}get hass(){return this._hass}_val(e,t=0){return this._state(`${this._prefix||De}${e}`,t)}_treeIcon(e){return e>=50?"mdi:forest":e>=10?"mdi:pine-tree":e>=1?"mdi:tree":"mdi:sprout"}render(){if(!this._config)return q;const e=this._theme(),t=this._val("flow_solar_to_home_energy")+this._val("flow_solar_to_ev_energy"),i=(.128*t).toFixed(1),s=`${t.toFixed(1)} kWh × 128 g/kWh`,r=this._val("yearly_trees_equivalent"),a=this._val("lifetime_trees_equivalent"),o=this._val("yearly_co2_avoided"),n=this._val("lifetime_co2_avoided"),l=r>=10?r.toFixed(0):r.toFixed(1),c=this._treeIcon(r);return W`
            <style>
                :host { display: block; }

                .wrap {
                    padding: 16px;
                    background:
                        radial-gradient(ellipse 70% 60% at 50% 25%, rgba(255,152,0,0.06) 0%, transparent 100%),
                        radial-gradient(circle at 2px 2px, ${e.dotColor} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI', 'Roboto', sans-serif;
                    color: var(--primary-text-color, ${e.text});
                }

                .tiles {
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                    gap: 12px;
                }

                .tile {
                    display: flex;
                    align-items: flex-start;
                    gap: 10px;
                    padding: 14px;
                    border-radius: 12px;
                    background: ${e.surface};
                    border: 1px solid ${e.surfaceBorder};
                }

                .tile ha-icon {
                    flex-shrink: 0;
                    margin-top: 2px;
                }

                .tile-content {
                    display: flex;
                    flex-direction: column;
                    gap: 4px;
                    min-width: 0;
                }

                .tile-label {
                    font-size: 12px;
                    font-weight: 500;
                    text-transform: uppercase;
                    letter-spacing: 0.3px;
                    color: var(--secondary-text-color, ${e.textSec});
                }

                .tile-hero {
                    font-size: 22px;
                    font-weight: 700;
                    font-variant-numeric: tabular-nums;
                    line-height: 1.1;
                }

                .tile-detail {
                    font-size: 12px;
                    color: var(--secondary-text-color, ${e.textSec});
                }

                .stats {
                    display: flex;
                    gap: 16px;
                    margin-top: 4px;
                    flex-wrap: wrap;
                }

                .stat {
                    display: flex;
                    flex-direction: column;
                    gap: 1px;
                }

                .stat-val {
                    font-size: 13px;
                    font-weight: 600;
                    font-variant-numeric: tabular-nums;
                }

                .stat-lbl {
                    font-size: 12px;
                    text-transform: uppercase;
                    letter-spacing: 0.3px;
                    color: var(--secondary-text-color, ${e.textSec});
                }

                /* Hidden SVG filter */
                .glow-svg {
                    position: absolute;
                    width: 0;
                    height: 0;
                    overflow: hidden;
                }

                @media (max-width: 480px) {
                    .tiles { grid-template-columns: 1fr; }
                }
            </style>

            <!-- SVG glow filter for leaf/tree icons -->
            <svg class="glow-svg" aria-hidden="true">
                <defs>
                    <filter id="leaf-glow" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="3" result="blur"/>
                        <feFlood flood-color="#8DC892" flood-opacity="0.25" result="color"/>
                        <feComposite in="color" in2="blur" operator="in" result="glow"/>
                        <feMerge>
                            <feMergeNode in="glow"/>
                            <feMergeNode in="SourceGraphic"/>
                        </feMerge>
                    </filter>
                </defs>
            </svg>

            <div class="wrap">
                <div class="tiles">

                    <!-- Left tile: Carbon Avoided Today -->
                    <div class="tile">
                        <ha-icon
                            icon="mdi:leaf"
                            style="--mdc-icon-size:24px;color:#8DC892;filter:url(#leaf-glow)"
                        ></ha-icon>
                        <div class="tile-content">
                            <span class="tile-label">${this._t("carbon_avoided_today")}</span>
                            <span class="tile-hero" style="color:#8DC892">${i} kg</span>
                            <span class="tile-detail">${s}</span>
                        </div>
                    </div>

                    <!-- Right tile: Trees Equivalent -->
                    <div class="tile">
                        <ha-icon
                            icon="${c}"
                            style="--mdc-icon-size:24px;color:#8DC892;filter:url(#leaf-glow)"
                        ></ha-icon>
                        <div class="tile-content">
                            <span class="tile-label">${this._t("trees_equivalent")}</span>
                            <span class="tile-hero" style="color:#8DC892">${l}</span>
                            <div class="stats">
                                <div class="stat">
                                    <span class="stat-val">${o.toFixed(0)} kg</span>
                                    <span class="stat-lbl">${this._t("co2_yearly")}</span>
                                </div>
                                <div class="stat">
                                    <span class="stat-val">${n.toFixed(0)} kg</span>
                                    <span class="stat-lbl">${this._t("co2_lifetime")}</span>
                                </div>
                                <div class="stat">
                                    <span class="stat-val">${a.toFixed(0)}</span>
                                    <span class="stat-lbl">${this._t("trees_lifetime")}</span>
                                </div>
                            </div>
                        </div>
                    </div>

                </div>
            </div>
        `}getCardSize(){return 3}static getStubConfig(){return{entity_prefix:De}}},{type:"custom:sem-energy-impact-card",name:"SEM Energy Impact Card",description:"Environmental impact display for Solar Energy Management",preview:!1});const Be="daily_ev_energy",Ne="lifetime_ev_energy",Ae="lifetime_ev_solar_share",Te="lifetime_ev_cost",Pe="lifetime_ev_sessions",Re="sensor.sem_";$e("sem-ev-progress-card",class extends ke{static get watchedEntities(){return[`${Re}${Be}`,`${Re}${Ne}`,`${Re}${Ae}`,`${Re}${Te}`,`${Re}${Pe}`,"number.sem_daily_ev_target","number.sem_charger_ev_charger_daily_ev_target"]}_evDailyTarget(){const e=this._hass?.states||{},t=Object.keys(e).filter(e=>/^number\.sem_charger_.+_daily_ev_target$/.test(e)).sort();if(t.length){const i=parseFloat(e[t[0]]?.state);if(!isNaN(i))return i}return this._state("number.sem_daily_ev_target",10)}setConfig(e){super.setConfig(e)}_prefix(){return this._config?.entity_prefix??Re}_pct(e,t){return t<=0?0:Math.min(100,e/t*100)}_barColor(e,t){return 0===e?"#666":t>=100?"#8DC892":t>=70?"#ff9800":"#f44336"}_fmtEnergy(e){return null==e||isNaN(e)?"—":e.toFixed(e<10?2:1)+" kWh"}_fmtCost(e,t){return null==e||isNaN(e)?"—":e.toFixed(2)+" "+t}_fmtSessions(e){return null==e||isNaN(e)?"—":String(Math.round(e))}render(){if(!this._hass||!this._config)return q;const e=this._theme(),t=this._prefix(),i=this._state(`${t}${Be}`),s=this._evDailyTarget(),r=this._state(`${t}${Ne}`),a=this._state(`${t}${Ae}`),o=this._state(`${t}${Te}`),n=this._state(`${t}${Pe}`),l=me(this._hass),c=this._pct(i,s),d=this._barColor(s,c),p=s>0?W`<span class="target-pct">${Math.round(c)}% ${this._t("of_target")}</span>`:W`<span class="target-pct no-target">${this._t("no_target")}</span>`,h=["radial-gradient(ellipse 80% 70% at 20% 50%, rgba(141,200,146,0.06) 0%, transparent 70%)",`radial-gradient(circle at 2px 2px, ${e.dotColor} 0.7px, transparent 0.7px)`].join(", ");return W`
            <style>
                :host {
                    display: block;
                    font-family: 'Segoe UI', 'Roboto', sans-serif;
                }

                .card {
                    background: ${e.cardBg};
                    background-image: ${h};
                    background-size: auto, 16px 16px;
                    border-radius: 12px;
                    padding: 16px;
                    box-shadow: ${e.shadow};
                    color: ${e.text};
                }

                /* ── Progress section ── */
                .progress-header {
                    display: flex;
                    align-items: center;
                    gap: 10px;
                    margin-bottom: 10px;
                }

                .ev-icon {
                    font-size: 22px;
                    color: #8DC892;
                    flex-shrink: 0;
                    display: flex;
                    align-items: center;
                }

                .ev-icon ha-icon {
                    --mdc-icon-size: 22px;
                    color: #8DC892;
                }

                .progress-info {
                    flex: 1;
                    min-width: 0;
                }

                .progress-label {
                    font-size: 13px;
                    font-weight: 600;
                    color: ${e.text};
                    letter-spacing: 0.3px;
                }

                .progress-values {
                    font-size: 12px;
                    color: ${e.textSec};
                    margin-top: 2px;
                }

                .target-pct {
                    font-size: 11px;
                    color: ${e.textSec};
                    margin-top: 1px;
                    display: block;
                }

                .no-target {
                    opacity: 0.6;
                    font-style: italic;
                }

                /* ── Progress bar ── */
                .progress-track {
                    height: 6px;
                    border-radius: 3px;
                    background: ${e.surface};
                    border: 1px solid ${e.surfaceBorder};
                    overflow: hidden;
                    margin-top: 10px;
                }

                .progress-fill {
                    height: 100%;
                    border-radius: 3px;
                    transition: width 0.5s ease, background 0.3s ease;
                }

                /* ── Section divider ── */
                .divider {
                    height: 1px;
                    background: ${e.divider};
                    margin: 14px 0;
                }

                /* ── Lifetime stats section ── */
                .lifetime-label {
                    font-size: 11px;
                    font-weight: 600;
                    text-transform: uppercase;
                    letter-spacing: 1px;
                    color: ${e.textSec};
                    margin-bottom: 10px;
                }

                .stats-grid {
                    display: grid;
                    grid-template-columns: 1fr 1fr 1fr 1fr;
                    gap: 8px;
                }

                @media (max-width: 400px) {
                    .stats-grid {
                        grid-template-columns: 1fr 1fr;
                    }
                }

                .stat-tile {
                    background: ${e.surface};
                    border: 1px solid ${e.surfaceBorder};
                    border-radius: 8px;
                    padding: 10px 8px;
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    gap: 4px;
                    text-align: center;
                }

                .stat-icon ha-icon {
                    --mdc-icon-size: 18px;
                    color: #8DC892;
                }

                .stat-value {
                    font-size: 13px;
                    font-weight: 700;
                    color: ${e.text};
                    line-height: 1.2;
                }

                .stat-label {
                    font-size: 11px;
                    color: ${e.textSec};
                    letter-spacing: 0.3px;
                    line-height: 1.2;
                }
            </style>

            <div class="card">
                <!-- Progress section -->
                <div class="progress-header">
                    <div class="ev-icon">
                        <ha-icon icon="mdi:car-electric"></ha-icon>
                    </div>
                    <div class="progress-info">
                        <div class="progress-label">${this._t("daily_progress")}</div>
                        <div class="progress-values">
                            ${this._fmtEnergy(i)}${s>0?` / ${this._fmtEnergy(s)}`:""}
                        </div>
                        ${p}
                    </div>
                </div>

                <div class="progress-track">
                    <div
                        class="progress-fill"
                        style="width:${c}%;background:${d}"
                    ></div>
                </div>

                <div class="divider"></div>

                <!-- Lifetime stats section -->
                <div class="lifetime-label">${this._t("lifetime_stats")}</div>
                <div class="stats-grid">
                    <div class="stat-tile">
                        <div class="stat-icon"><ha-icon icon="mdi:lightning-bolt"></ha-icon></div>
                        <div class="stat-value">${this._fmtEnergy(r)}</div>
                        <div class="stat-label">${this._t("energy")}</div>
                    </div>
                    <div class="stat-tile">
                        <div class="stat-icon"><ha-icon icon="mdi:weather-sunny"></ha-icon></div>
                        <div class="stat-value">${Math.round(a)}%</div>
                        <div class="stat-label">${this._t("solar")}</div>
                    </div>
                    <div class="stat-tile">
                        <div class="stat-icon"><ha-icon icon="mdi:currency-usd"></ha-icon></div>
                        <div class="stat-value">${this._fmtCost(o,l)}</div>
                        <div class="stat-label">${this._t("cost")}</div>
                    </div>
                    <div class="stat-tile">
                        <div class="stat-icon"><ha-icon icon="mdi:counter"></ha-icon></div>
                        <div class="stat-value">${this._fmtSessions(n)}</div>
                        <div class="stat-label">${this._t("sessions")}</div>
                    </div>
                </div>
            </div>
        `}getCardSize(){return 3}static getStubConfig(){return{entity_prefix:Re}}},{type:"sem-ev-progress-card",name:"SEM EV Progress Card",description:"Daily EV progress bar and lifetime charging statistics"});$e("sem-gauge-card",class extends ke{static get watchedEntities(){return[]}setConfig(e){if(!e.entity)throw new Error("sem-gauge-card requires entity");super.setConfig(e),this._entity=e.entity,this._name=e.name||null,this._min=e.min??0,this._max=e.max??100,this._color=e.color||"#4db6ac",this._unit=e.unit||"%"}set hass(e){this._hass,this._hass=e;const t=e?.states[this._entity]?.state;t!==this._lastState&&(this._lastState=t,this.requestUpdate())}get hass(){return this._hass}render(){if(!this._hass||!this._config)return q;const e=this._hass.states[this._entity],t=e&&parseFloat(e.state)||0,i=this._name||e?.attributes?.friendly_name||this._entity,s=Math.min(Math.max((t-this._min)/(this._max-this._min),0),1),r=this._theme(),a=this._color,o=58,n=-210,l=n+240*s,c=e=>{const t=e*Math.PI/180;return{x:70+o*Math.cos(t),y:70+o*Math.sin(t)}},d=c(n),p=c(30),h=c(l),_=240*s>180?1:0,g=s<.5?`color-mix(in srgb, #f44336 ${Math.round(100*(1-2*s))}%, #ff9800)`:`color-mix(in srgb, ${a} ${Math.round(2*(s-.5)*100)}%, #ff9800)`;return W`
            <ha-card>
                <div class="gauge-wrap">
                    <svg viewBox="0 0 140 100" xmlns="http://www.w3.org/2000/svg">
                        <defs>
                            <filter id="glow-${this._entity.replace(/\./g,"_")}" x="-20%" y="-20%" width="140%" height="140%">
                                <feGaussianBlur stdDeviation="3" result="blur"/>
                                <feFlood flood-color="${g}" flood-opacity="0.3"/>
                                <feComposite in2="blur" operator="in"/>
                                <feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge>
                            </filter>
                        </defs>
                        <!-- Background arc -->
                        <path d="M ${d.x} ${d.y} A ${o} ${o} 0 ${1} 1 ${p.x} ${p.y}"
                              fill="none" stroke="${r.surface||"rgba(255,255,255,0.08)"}" stroke-width="8"
                              stroke-linecap="round"/>
                        <!-- Value arc -->
                        ${s>.01?j`
                            <path d="M ${d.x} ${d.y} A ${o} ${o} 0 ${_} 1 ${h.x} ${h.y}"
                                  fill="none" stroke="${g}" stroke-width="8"
                                  stroke-linecap="round"
                                  filter="url(#glow-${this._entity.replace(/\./g,"_")})"
                                  style="transition: d 1s ease"/>
                        `:""}
                    </svg>
                    <div class="gauge-center">
                        <span class="gauge-value" style="color:${g}">${t.toFixed(1)}${this._unit}</span>
                    </div>
                    <div class="gauge-label">${i}</div>
                </div>
            </ha-card>
        `}static get styles(){return a`
            :host { display: block; }
            ha-card {
                background: transparent !important;
                border: none !important;
                box-shadow: none !important;
            }
            .gauge-wrap {
                position: relative;
                display: flex;
                flex-direction: column;
                align-items: center;
                padding: 16px 16px 8px;
            }
            svg {
                width: 180px;
                height: 130px;
            }
            .gauge-center {
                position: absolute;
                top: 65px;
                left: 50%;
                transform: translateX(-50%);
                text-align: center;
            }
            .gauge-value {
                font-size: 28px;
                font-weight: 700;
                font-variant-numeric: tabular-nums;
                font-family: 'Segoe UI', 'Roboto', sans-serif;
            }
            .gauge-label {
                font-size: 13px;
                font-weight: 500;
                color: var(--secondary-text-color, #9e9e9e);
                text-align: center;
                margin-top: -8px;
                font-family: 'Segoe UI', 'Roboto', sans-serif;
            }
        `}getCardSize(){return 3}static getStubConfig(){return{entity:"sensor.sem_self_consumption_rate"}}},{type:"custom:sem-gauge-card",name:"SEM Gauge Card",description:"Lumina-styled arc gauge for percentage values",preview:!1});const Le="sensor.sem_",Oe=["solar_power","daily_solar_energy","monthly_solar_yield_energy","yearly_solar_yield_energy","flow_solar_to_home_power","flow_solar_to_battery_power","flow_solar_to_ev_power","flow_solar_to_grid_power","flow_solar_to_home_energy","flow_solar_to_battery_energy","flow_solar_to_ev_energy","flow_solar_to_grid_energy","forecast_today_kwh","forecast_tomorrow_kwh","forecast_remaining_today_kwh","forecast_peak_power_today_w","forecast_peak_time_today","best_surplus_window","pv_daily_specific_yield","pv_performance_vs_forecast","pv_estimated_annual_degradation","pv_degradation_trend","pv_string_pv1_power","pv_string_pv1_daily_energy","pv_string_pv2_power","pv_string_pv2_daily_energy","pv_string_pv3_power","pv_string_pv3_daily_energy","pv_string_pv4_power","pv_string_pv4_daily_energy"];function Ue(e){return Oe.map(t=>`${e}${t}`)}$e("sem-solar-card",class extends ke{static get styles(){return[we]}static get watchedEntities(){return Ue(Le)}setConfig(e){super.setConfig(e),this._prefix=e.entity_prefix||Le,this._prefix!==Le&&(this._prevVals={})}set hass(e){this._hass=e;const t=e?.language,i="function"==typeof semLocalize;let s=!1;if((t!==this._lang||i&&!this._localizeReady)&&(this._lang=t,this._localizeReady=i,s=!0),this._isFrozen()&&!s)return;const r=Ue(this._prefix||Le);let a=!1;for(const t of r)if(this._prevVals[t]!==e.states[t]?.state){a=!0;break}if(a||s){for(const t of r)this._prevVals[t]=e.states[t]?.state;this._scheduleUpdate()}}get hass(){return this._hass}_val(e,t=0){return this._state(`${this._prefix}${e}`,t)}_valStr(e){return this._stateStr(`${this._prefix}${e}`)}_fmt(e,t=1){return null==e||isNaN(e)?"—":e.toFixed(t)}render(){if(!this._config)return q;const e=this._theme(),t=this._val("solar_power"),i=this._val("daily_solar_energy"),s=this._val("monthly_solar_yield_energy"),r=this._val("yearly_solar_yield_energy"),a=Math.min(Math.max(t/1e4,0),1),o=2*Math.PI*42,n=(o*(1-a)).toFixed(1),l=t>50?"solarPulse 3s ease-in-out infinite":"none",c=this._val("flow_solar_to_home_power"),d=this._val("flow_solar_to_home_energy"),p=this._val("flow_solar_to_battery_power"),h=this._val("flow_solar_to_battery_energy"),_=this._val("flow_solar_to_ev_power"),g=this._val("flow_solar_to_ev_energy"),u=this._val("flow_solar_to_grid_power"),f=this._val("flow_solar_to_grid_energy"),m=this._val("forecast_today_kwh"),y=this._val("forecast_tomorrow_kwh"),v=this._val("forecast_remaining_today_kwh"),x=this._val("forecast_peak_power_today_w"),b=this._valStr("forecast_peak_time_today"),$=this._valStr("best_surplus_window"),w=this._val("pv_daily_specific_yield"),k=this._val("pv_performance_vs_forecast"),S=this._val("pv_estimated_annual_degradation"),C=this._valStr("pv_degradation_trend"),z=0!==k?this._fmt(k,0)+"%":"—",M=k>=0?"#8DC892":"#f06292",E=xe(this._hass,this._prefix);return W`
            <style>
                :host { display: block; }
                .wrap {
                    padding: 16px 20px;
                    position: relative;
                    background: ${ye(e,pe.solar)};
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${e.text});
                }
                .glow-svg { position: absolute; width: 0; height: 0; overflow: hidden; }

                /* ── Hero ── */
                .hero { display: flex; align-items: center; gap: 20px; }
                @media (max-width: 400px) { .hero { flex-direction: column; gap: 12px; } }

                .solar-ring { position: relative; width: 100px; height: 100px; flex-shrink: 0; }
                .solar-ring svg { width: 100%; height: 100%; transform: rotate(-90deg); }
                .ring-bg { fill: none; stroke: rgba(255,152,0,0.12); stroke-width: 5; }
                .solar-arc {
                    fill: none; stroke: #ff9800; stroke-width: 5; stroke-linecap: round;
                    transition: stroke-dashoffset 1.5s cubic-bezier(0.4,0,0.2,1);
                    filter: url(#solar-glow);
                }
                .solar-glow-ring {
                    fill: none; stroke: #ff9800; stroke-width: 8; opacity: 0.2;
                    filter: url(#solar-glow-soft);
                }
                @keyframes solarPulse { 0%,100%{opacity:1}50%{opacity:0.6} }

                .ring-center {
                    position: absolute; top: 50%; left: 50%;
                    transform: translate(-50%, -50%);
                    text-align: center; pointer-events: none;
                }
                .solar-power-value {
                    font-size: 13px; font-weight: 700;
                    font-variant-numeric: tabular-nums;
                    color: #ff9800;
                    text-shadow: 0 0 8px rgba(255,152,0,0.35);
                    line-height: 1.2;
                }
                .solar-daily-value {
                    font-size: 11px; color: var(--secondary-text-color,${e.textSec});
                    font-variant-numeric: tabular-nums;
                }

                /* ── Section ── */
                .section {
                    margin-top: 12px;
                    padding: 10px 12px;
                    background: var(--secondary-background-color, ${e.surface});
                    border: 1px solid var(--divider-color, ${e.surfaceBorder});
                    border-radius: 10px;
                }
                .section-title {
                    font-size: 12px; font-weight: 600; text-transform: uppercase;
                    letter-spacing: 0.6px; color: #ff9800; margin-bottom: 8px;
                }

                /* ── Flows grid ── */
                .flows-grid {
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                    gap: 8px 24px;
                }
                .flow-row { display: flex; align-items: center; gap: 6px; }
                .flow-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
                .flow-label { font-size: 12px; color: var(--secondary-text-color,${e.textSec}); flex: 1; }
                .flow-vals { text-align: right; }
                .flow-power {
                    font-size: 13px; font-weight: 600;
                    font-variant-numeric: tabular-nums;
                    color: var(--primary-text-color,${e.text});
                }
                .flow-energy {
                    font-size: 11px; color: var(--secondary-text-color,${e.textSec});
                    font-variant-numeric: tabular-nums;
                }

                /* ── Two-column section ── */
                .two-col {
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                    gap: 0 20px;
                }
                @media (max-width: 400px) { .two-col { grid-template-columns: 1fr; } }

                /* Mobile polish (added during the same fix as the
                   render-bug repair): the existing 400px breakpoints
                   only handle the very narrowest phones. The card is
                   noticeably cramped on a typical 375–480px viewport
                   without these — the 2-col flows grid produces two
                   ~155px columns of dense kWh data. */
                @media (max-width: 480px) {
                    .hero { flex-direction: column; gap: 12px; align-items: stretch; }
                    .solar-ring { width: 90px; height: 90px; margin: 0 auto; }
                    .flows-grid { grid-template-columns: 1fr; gap: 6px; }
                    .section { padding: 8px 10px; margin-top: 10px; }
                    .metric-row { padding: 1px 0; }
                    .chip { padding: 5px 6px; }
                    .chip-value { font-size: 12px; }
                }

                /* ── Metric rows ── */
                .metric-row {
                    display: flex; justify-content: space-between; align-items: baseline;
                    padding: 2px 0;
                }
                .metric-label {
                    font-size: 12px; color: var(--secondary-text-color,${e.textSec});
                    font-weight: 500;
                }
                .metric-val {
                    font-size: 13px; font-weight: 600;
                    font-variant-numeric: tabular-nums;
                    color: var(--primary-text-color,${e.text});
                }

                /* ── Monthly / yearly chips ── */
                .chips { display: flex; gap: 8px; margin-top: 10px; }
                .chip {
                    flex: 1; text-align: center; padding: 7px 8px;
                    background: var(--secondary-background-color, ${e.surface});
                    border: 1px solid var(--divider-color, ${e.surfaceBorder});
                    border-radius: 10px;
                }
                .chip-label {
                    font-size: 12px; color: var(--secondary-text-color,${e.textTertiary});
                    font-weight: 500; margin-bottom: 2px;
                }
                .chip-value {
                    font-size: 14px; font-weight: 600; color: #ff9800;
                    font-variant-numeric: tabular-nums;
                }
                /* v1.7.1 / #312: per-PV-string chip strip styles */
                ${be}
            </style>

            <!-- SVG glow filters -->
            <svg class="glow-svg" aria-hidden="true">
                <defs>
                    <filter id="solar-glow" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="4" result="blur"/>
                        <feFlood flood-color="#ff9800" flood-opacity="0.3" result="color"/>
                        <feComposite in="color" in2="blur" operator="in" result="glow"/>
                        <feMerge><feMergeNode in="glow"/><feMergeNode in="SourceGraphic"/></feMerge>
                    </filter>
                    <filter id="solar-glow-soft" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="6" result="blur"/>
                        <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
                    </filter>
                </defs>
            </svg>

            <ha-card>
                <div class="wrap">

                    <!-- v1.7.1 / #312: per-PV-string chip strip (auto-shown ≥ 2 strings) -->
                    ${E.length>=2?W`
                        <div class="pv-strings-row">
                            ${E.map(e=>W`
                                <div class="pv-chip"
                                     title="${e.entityId}"
                                     data-entity="${e.entityId}"
                                     @click=${()=>this._fireMoreInfo?.(e.entityId)}>
                                    <span class="pv-chip-label">${e.name}</span>
                                    <span class="pv-chip-value">${(Math.abs(e.watts)/1e3).toFixed(2)} kW</span>
                                </div>
                            `)}
                        </div>
                    `:q}

                    <!-- Hero -->
                    <div class="hero">
                        <div class="solar-ring">
                            <svg viewBox="0 0 100 100">
                                <circle class="solar-glow-ring" cx="50" cy="50" r="42">
                                    <animate attributeName="opacity" values="0.2;0.07;0.2" dur="4s" repeatCount="indefinite"/>
                                </circle>
                                <circle class="ring-bg" cx="50" cy="50" r="42"/>
                                <circle class="solar-arc" cx="50" cy="50" r="42"
                                    stroke-dasharray="${o.toFixed(1)}"
                                    style="stroke-dashoffset:${n};animation:${l}"/>
                            </svg>
                            <div class="ring-center">
                                <ha-icon icon="mdi:solar-power" style="--mdc-icon-size:22px;color:#ff9800;opacity:0.8"></ha-icon>
                                <div class="solar-power-value">${ge(t)}</div>
                                <div class="solar-daily-value">${this._fmt(i,2)} kWh</div>
                            </div>
                        </div>

                        <!-- Monthly + Yearly chips -->
                        <div style="flex:1;min-width:0">
                            <div class="chips" style="margin-top:0">
                                <div class="chip">
                                    <div class="chip-label">${this._t("monthly")}</div>
                                    <div class="chip-value">${this._fmt(s,1)} kWh</div>
                                </div>
                                <div class="chip">
                                    <div class="chip-label">${this._t("yearly")}</div>
                                    <div class="chip-value">${this._fmt(r,1)} kWh</div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Today's Flows -->
                    <div class="section">
                        <div class="section-title">${this._t("solar_flows_today")}</div>
                        <div class="flows-grid">
                            <div class="flow-row">
                                <div class="flow-dot" style="background:#5BC8D8"></div>
                                <span class="flow-label">${this._t("home")}</span>
                                <div class="flow-vals">
                                    <div class="flow-power">${ge(c)}</div>
                                    <div class="flow-energy">${this._fmt(d,2)} kWh</div>
                                </div>
                            </div>
                            <div class="flow-row">
                                <div class="flow-dot" style="background:#f06292"></div>
                                <span class="flow-label">${this._t("battery")}</span>
                                <div class="flow-vals">
                                    <div class="flow-power">${ge(p)}</div>
                                    <div class="flow-energy">${this._fmt(h,2)} kWh</div>
                                </div>
                            </div>
                            <div class="flow-row">
                                <div class="flow-dot" style="background:#8DC892"></div>
                                <span class="flow-label">${this._t("ev")}</span>
                                <div class="flow-vals">
                                    <div class="flow-power">${ge(_)}</div>
                                    <div class="flow-energy">${this._fmt(g,2)} kWh</div>
                                </div>
                            </div>
                            <div class="flow-row">
                                <div class="flow-dot" style="background:#8353d1"></div>
                                <span class="flow-label">${this._t("grid_export")}</span>
                                <div class="flow-vals">
                                    <div class="flow-power">${ge(u)}</div>
                                    <div class="flow-energy">${this._fmt(f,2)} kWh</div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- v1.7.0 / #312: per-PV-string detail. Reuses
                         the "flow row" style for visual consistency
                         with the Today's Flows section above. Auto-
                         shown when 2+ strings are present; collapses
                         to nothing on single-string installs.
                         (Do NOT quote "nothing" with backticks here;
                         this HTML comment lives inside an html
                         tagged template literal, and a stray
                         backtick terminates that template at parse
                         time — see the 0x0 render bug we fixed.) -->
                    ${E.length>=2?W`
                        <div class="section">
                            <div class="section-title">${this._t("pv_strings_today")||"Per string today"}</div>
                            <div class="flows-grid">
                                ${E.map(e=>W`
                                    <div class="flow-row"
                                         style="cursor:pointer"
                                         @click=${()=>this._fireMoreInfo?.(e.entityId)}>
                                        <div class="flow-dot" style="background:#ff9800"></div>
                                        <span class="flow-label">${e.name}</span>
                                        <div class="flow-vals">
                                            <div class="flow-power">${ge(e.watts)}</div>
                                            <div class="flow-energy">${null!=e.energyKwh?this._fmt(e.energyKwh,2)+" kWh":"—"}</div>
                                        </div>
                                    </div>
                                `)}
                            </div>
                        </div>
                    `:q}

                    <!-- Forecast + Performance (side by side) -->
                    <div class="section two-col">
                        <div>
                            <div class="section-title">${this._t("forecast")}</div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("today")}</span>
                                <span class="metric-val">${this._fmt(m,1)} kWh</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("tomorrow")}</span>
                                <span class="metric-val">${this._fmt(y,1)} kWh</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("remaining")}</span>
                                <span class="metric-val">${this._fmt(v,1)} kWh</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("peak_power")}</span>
                                <span class="metric-val">
                                    ${x>0?ge(x):"—"}
                                    <span style="font-size:11px;opacity:0.7;margin-left:4px">${b||"—"}</span>
                                </span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("best_surplus_window")}</span>
                                <span class="metric-val" style="color:#ff9800;font-size:11px">${$||"—"}</span>
                            </div>
                        </div>
                        <div>
                            <div class="section-title">${this._t("performance")}</div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("specific_yield")}</span>
                                <span class="metric-val">${w>0?this._fmt(w,2)+" kWh/kWp":"—"}</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("vs_forecast")}</span>
                                <span class="metric-val" style="color:${M}">${z}</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("degradation")}</span>
                                <span class="metric-val">${0!==S?this._fmt(S,2)+"%/yr":"—"}</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("trend")}</span>
                                <span class="metric-val">${C?this._t(C):"—"}</span>
                            </div>
                        </div>
                    </div>

                </div>
            </ha-card>
        `}getCardSize(){return 5}static getStubConfig(){return{entity_prefix:Le}}},{type:"sem-solar-card",name:"SEM Solar",description:"Consolidated solar production card with flows, forecast, and performance metrics"});const He=["sensor.sem_daily_solar_energy","sensor.sem_solar_power"];$e("sem-solar-kpi-card",class extends ke{static get watchedEntities(){return He}setConfig(e){super.setConfig(e),this._prefix=e.entity_prefix||"sensor.sem_"}_val(e,t=0){const i=this._hass?.states[`${this._prefix}${e}`];if(!i||"unavailable"===i.state||"unknown"===i.state)return t;const s=parseFloat(i.state);return Number.isFinite(s)?s:t}static get styles(){return a`
                :host { display: block; }
                .kpi {
                    display: flex;
                    align-items: center;
                    gap: 18px;
                    padding: 18px 22px;
                }
                .kpi-icon {
                    flex: 0 0 auto;
                    width: 52px;
                    height: 52px;
                    border-radius: 14px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    background: rgba(255, 152, 0, 0.14);
                }
                .kpi-icon ha-icon {
                    color: #ff9800;
                    --mdc-icon-size: 32px;
                }
                .kpi-main { flex: 1 1 auto; min-width: 0; }
                .kpi-value {
                    font-size: 2.6rem;
                    font-weight: 700;
                    line-height: 1.1;
                    color: #ff9800;
                    letter-spacing: -0.5px;
                    white-space: nowrap;
                }
                .kpi-value .unit {
                    font-size: 1.3rem;
                    font-weight: 500;
                    opacity: 0.85;
                    margin-left: 4px;
                }
                .kpi-label {
                    margin-top: 2px;
                    font-size: 0.85rem;
                    color: var(--secondary-text-color);
                    text-transform: uppercase;
                    letter-spacing: 0.6px;
                }
                .kpi-now {
                    flex: 0 0 auto;
                    display: flex;
                    align-items: center;
                    gap: 6px;
                    padding: 6px 12px;
                    border-radius: 999px;
                    background: var(--secondary-background-color, rgba(255,255,255,0.06));
                    font-size: 0.9rem;
                    color: var(--primary-text-color);
                }
                .kpi-now ha-icon {
                    color: #ff9800;
                    --mdc-icon-size: 16px;
                }
                @media (max-width: 460px) {
                    .kpi { padding: 14px 16px; gap: 12px; }
                    .kpi-value { font-size: 2.1rem; }
                    .kpi-icon { width: 44px; height: 44px; }
                }
            `}render(){if(!this._hass)return q;const e=this._val("daily_solar_energy"),t=this._val("solar_power");return W`
            <ha-card>
                <div class="kpi">
                    <div class="kpi-icon"><ha-icon icon="mdi:solar-power-variant"></ha-icon></div>
                    <div class="kpi-main">
                        <div class="kpi-value">${e.toFixed(1)}<span class="unit">kWh</span></div>
                        <div class="kpi-label">${this._t("todays_solar_production")}</div>
                    </div>
                    ${t>0?W`
                        <div class="kpi-now">
                            <ha-icon icon="mdi:white-balance-sunny"></ha-icon>
                            <span>${ge(t)}</span>
                        </div>
                    `:q}
                </div>
            </ha-card>
        `}getCardSize(){return 1}static getStubConfig(){return{}}},{type:"custom:sem-solar-kpi-card",name:"SEM Solar KPI Card",description:"Prominent Today's Solar Production KPI for the Home tab",preview:!0});const We="sensor.sem_",je=["solar_power","daily_solar_energy","monthly_solar_yield_energy","forecast_today_kwh","forecast_tomorrow_kwh","self_consumption_rate","autarky_rate","daily_costs","daily_savings","daily_ev_energy","daily_grid_import_energy"];function Ge(e){return je.map(t=>`${e}${t}`)}$e("sem-solar-summary-card",class extends ke{static get watchedEntities(){return Ge(We)}setConfig(e){super.setConfig(e),this._prefix=e.entity_prefix||We,this._prefix!==We&&(this._prevVals={})}set hass(e){this._hass=e;const t=e?.language,i="function"==typeof semLocalize;let s=!1;if((t!==this._lang||i&&!this._localizeReady)&&(this._lang=t,this._localizeReady=i,s=!0),this._isFrozen()&&!s)return;const r=Ge(this._prefix||We);let a=!1;for(const t of r)if(this._prevVals[t]!==e.states[t]?.state){a=!0;break}if(a||s){for(const t of r)this._prevVals[t]=e.states[t]?.state;this._scheduleUpdate()}}get hass(){return this._hass}_val(e,t=0){return this._state(`${this._prefix}${e}`,t)}_valStr(e){return this._stateStr(`${this._prefix}${e}`)}_fmt(e,t=1){return null==e||isNaN(e)?"—":e.toFixed(t)}render(){if(!this._config)return q;const e=this._theme(),t=this._val("solar_power"),i=this._val("daily_solar_energy"),s=this._val("monthly_solar_yield_energy"),r=this._val("forecast_today_kwh"),a=this._val("forecast_tomorrow_kwh"),o=this._val("self_consumption_rate"),n=this._val("autarky_rate"),l=this._val("daily_costs"),c=this._val("daily_savings"),d=this._val("daily_ev_energy"),p=this._val("daily_grid_import_energy"),h=me(this._hass),_=(.15+.6*Math.min(t/1e4,1)).toFixed(3),g=2*Math.PI*42,u=(g*(1-(r>0?Math.min(i/r,1):0))).toFixed(1);return W`
            <style>
                :host { display: block; }
                .wrap {
                    padding: 16px 20px;
                    position: relative;
                    background:
                        radial-gradient(ellipse 70% 60% at 50% 25%, rgba(255,152,0,0.06) 0%, transparent 100%),
                        radial-gradient(circle at 2px 2px, ${e.dotColor} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${e.text});
                }
                .glow-svg { position: absolute; width: 0; height: 0; overflow: hidden; }

                /* Hero section */
                .hero {
                    display: flex;
                    align-items: center;
                    gap: 20px;
                    margin-bottom: 20px;
                }
                .solar-ring {
                    position: relative;
                    width: 100px;
                    height: 100px;
                    flex-shrink: 0;
                }
                .solar-ring svg {
                    width: 100%;
                    height: 100%;
                    transform: rotate(-90deg);
                }
                .ring-bg {
                    fill: none;
                    stroke: rgba(255,152,0,0.12);
                    stroke-width: 5;
                }
                .progress-arc {
                    fill: none;
                    stroke: #ff9800;
                    stroke-width: 5;
                    stroke-linecap: round;
                    transition: stroke-dashoffset 1.5s cubic-bezier(0.4,0,0.2,1);
                    filter: url(#solar-glow);
                }
                .ring-icon {
                    position: absolute;
                    top: 50%;
                    left: 50%;
                    transform: translate(-50%, -50%);
                    text-align: center;
                }
                .ring-icon .power {
                    font-size: 18px;
                    font-weight: 700;
                    font-variant-numeric: tabular-nums;
                    color: #ff9800;
                    text-shadow: 0 0 8px rgba(255,152,0,0.3);
                }
                .ring-icon .label {
                    font-size: 11px;
                    color: rgba(255,152,0,0.6);
                    font-weight: 500;
                    letter-spacing: 1px;
                    text-transform: uppercase;
                }
                .hero-stats {
                    flex: 1;
                    min-width: 0;
                }
                .hero-title {
                    font-size: 13px;
                    font-weight: 600;
                    color: rgba(255,152,0,0.85);
                    letter-spacing: 0.5px;
                    margin-bottom: 8px;
                }
                .hero-row {
                    display: flex;
                    justify-content: space-between;
                    align-items: baseline;
                    padding: 3px 0;
                }
                .hero-label {
                    font-size: 12px;
                    color: var(--secondary-text-color, ${e.textSec});
                    font-weight: 500;
                }
                .hero-value {
                    font-size: 13px;
                    font-weight: 600;
                    font-variant-numeric: tabular-nums;
                }

                /* Metrics grid */
                .metrics {
                    display: grid;
                    grid-template-columns: repeat(3, 1fr);
                    gap: 10px;
                }
                .metric {
                    background: var(--secondary-background-color, ${e.surface});
                    border: 1px solid var(--divider-color, ${e.surfaceBorder});
                    border-radius: 10px;
                    padding: 10px;
                    text-align: center;
                    transition: border-color 0.3s cubic-bezier(0.4,0,0.2,1);
                }
                .metric:hover {
                    border-color: var(--divider-color, ${e.surfaceHover});
                }
                .metric-label {
                    font-size: 11px;
                    color: var(--secondary-text-color, ${e.textTertiary});
                    font-weight: 500;
                    letter-spacing: 0.3px;
                    margin-bottom: 4px;
                }
                .metric-value {
                    font-size: 14px;
                    font-weight: 600;
                    font-variant-numeric: tabular-nums;
                }
                .c-solar   { color: #ff9800; }
                .c-grid    { color: #488fc2; }
                .c-ev      { color: #8DC892; }
                .c-home    { color: #5BC8D8; }
                .c-savings { color: #4db6ac; }
                .c-cost    { color: #f06292; }
            </style>

            <!-- SVG glow filters -->
            <svg class="glow-svg" aria-hidden="true">
                <defs>
                    <filter id="solar-glow" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="3" result="blur"/>
                        <feFlood flood-color="#ff9800" flood-opacity="0.25" result="color"/>
                        <feComposite in="color" in2="blur" operator="in" result="glow"/>
                        <feMerge><feMergeNode in="glow"/><feMergeNode in="SourceGraphic"/></feMerge>
                    </filter>
                    <filter id="solar-glow-soft" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="6" result="blur"/>
                        <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
                    </filter>
                </defs>
            </svg>

            <ha-card>
                <div class="wrap">

                    <!-- Hero -->
                    <div class="hero">
                        <div class="solar-ring">
                            <svg viewBox="0 0 100 100">
                                <circle cx="50" cy="50" r="42"
                                    fill="none" stroke="#ff9800" stroke-width="8"
                                    filter="url(#solar-glow-soft)"
                                    style="opacity:${_}">
                                    <animate attributeName="r" values="42;45;42" dur="3s" repeatCount="indefinite"/>
                                    <animate attributeName="opacity" values="${_};${(.4*parseFloat(_)).toFixed(3)};${_}" dur="3s" repeatCount="indefinite"/>
                                </circle>
                                <circle class="ring-bg" cx="50" cy="50" r="42"/>
                                <circle class="progress-arc" cx="50" cy="50" r="42"
                                    stroke-dasharray="${g.toFixed(1)}"
                                    style="stroke-dashoffset:${u}"/>
                            </svg>
                            <div class="ring-icon">
                                <div class="power">${ge(t)}</div>
                                <div class="label">${this._t("solar").toUpperCase()}</div>
                            </div>
                        </div>

                        <div class="hero-stats">
                            <div class="hero-title">${this._t("production")}</div>
                            <div class="hero-row">
                                <span class="hero-label">${this._t("yield_today")}</span>
                                <span class="hero-value c-solar">${this._fmt(i,2)} kWh</span>
                            </div>
                            <div class="hero-row">
                                <span class="hero-label">${this._t("grid_today")}</span>
                                <span class="hero-value c-grid">${this._fmt(p,2)} kWh</span>
                            </div>
                            <div class="hero-row">
                                <span class="hero-label">${this._t("forecast")}</span>
                                <span class="hero-value c-solar">${this._fmt(r,1)} kWh</span>
                            </div>
                            <div class="hero-row">
                                <span class="hero-label">${this._t("tomorrow")}</span>
                                <span class="hero-value" style="color:var(--secondary-text-color)">${this._fmt(a,1)} kWh</span>
                            </div>
                        </div>
                    </div>

                    <!-- Metrics 3x2 grid -->
                    <div class="metrics">
                        <div class="metric">
                            <div class="metric-label">${this._t("self_use")}</div>
                            <div class="metric-value c-home">${this._fmt(o,1)}%</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">${this._t("autarky")}</div>
                            <div class="metric-value c-savings">${this._fmt(n,1)}%</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">${this._t("ev_today")}</div>
                            <div class="metric-value c-ev">${this._fmt(d,1)} kWh</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">${this._t("cost")}</div>
                            <div class="metric-value c-cost">${this._fmt(l,2)} ${h}</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">${this._t("saved")}</div>
                            <div class="metric-value c-savings">${this._fmt(c,2)} ${h}</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">${this._t("monthly")}</div>
                            <div class="metric-value c-solar">${this._fmt(s,1)} kWh</div>
                        </div>
                    </div>

                </div>
            </ha-card>
        `}getCardSize(){return 4}static getStubConfig(){return{entity_prefix:We}}},{type:"sem-solar-summary-card",name:"SEM Solar Summary",description:"Lumina-styled solar overview with glow ring and production metrics"});const qe="sensor.sem_",Ke=["battery_soc","battery_power","battery_charge_power","battery_discharge_power","battery_status","battery_health_score","battery_cycles_estimated","battery_temperature","battery_session_type","battery_session_energy","battery_session_solar_share","battery_session_duration","battery_session_avg_power","battery_session_cost","battery_session_savings","daily_battery_charge_energy","daily_battery_discharge_energy","daily_battery_savings","flow_solar_to_battery_energy","flow_grid_to_battery_energy","monthly_battery_charge_energy","monthly_battery_discharge_energy"],Ve=["#4db6ac","#FFB74D","#BA68C8","#64B5F6"];$e("sem-battery-card",class extends ke{constructor(){super(),this._batteries=[],this._lastStateCount=0}static get watchedEntities(){return Ke.map(e=>`${qe}${e}`)}setConfig(e){super.setConfig(e),this._prefix=e.entity_prefix||qe}set hass(e){this._hass=e;const t=e?.language,i="function"==typeof semLocalize;let s=!1;(t!==this._lang||i&&!this._localizeReady)&&(this._lang=t,this._localizeReady=i,s=!0);const r=Object.keys(e.states).length;if(r!==this._lastStateCount){this._lastStateCount=r;const t=[];for(const i of Object.keys(e.states)){const e=i.match(/^sensor\.sem_battery_(b\d+)_power$/);e&&t.push(e[1])}t.sort(),this._batteries=t}if(this._isFrozen()&&!s)return;const a=e?.states[`${this._prefix}battery_status`]?.state;if(("unavailable"===a||"unknown"===a)&&!s)return;let o=Ke.map(t=>e?.states[`${this._prefix}${t}`]?.state||"").join(",")+"|"+t;this._batteries.length?o+="|"+this._batteries.map(t=>{const i=[`battery_${t}_power`,`battery_${t}_soc`,`battery_${t}_status`,`battery_${t}_capacity_kwh`].map(t=>e?.states[`${this._prefix}${t}`]?.state||"").join(":"),s=[`select.sem_battery_${t}_mode`,`number.sem_battery_${t}_reserve_soc`].map(t=>e?.states[t]?.state||"").join(":");return i+":"+s}).join("|"):o+="|"+["select.sem_battery_mode","number.sem_battery_reserve_soc"].map(t=>e?.states[t]?.state||"").join(":"),(o!==this._lastBattKey||s)&&(this._lastBattKey=o,this._scheduleUpdate())}get hass(){return this._hass}_val(e,t=0){return this._state(`${this._prefix}${e}`,t)}_valStr(e){return this._stateStr(`${this._prefix}${e}`)}_fmt(e,t=1){return null==e||isNaN(e)?"—":e.toFixed(t)}_fmtDuration(e){if(null==e||isNaN(e))return"—";const t=Math.round(e);if(t<90)return`${t} min`;const i=Math.floor(t/60),s=t-60*i;return 0===s?`${i} h`:`${i} h ${s} min`}_batteryName(e){const t=this._hass?.states[`${this._prefix}battery_${e}_power`];let i=e.toUpperCase();return t?.attributes?.friendly_name&&(i=t.attributes.friendly_name.replace(/^SEM\s+/i,"").replace(/\s+Power$/i,"")),i}_renderMiniSocRing(e,t){const i=null!=e?Math.max(0,Math.min(100,e)):0,s=2*Math.PI*22,r=s*(1-i/100);return W`
            <svg viewBox="0 0 56 56" width="56" height="56"
                 style="display:block;">
                <circle cx="28" cy="28" r="${22}" fill="none"
                        stroke="rgba(255,255,255,0.12)" stroke-width="4" />
                <circle cx="28" cy="28" r="${22}" fill="none"
                        stroke="${t}" stroke-width="4"
                        stroke-linecap="round"
                        stroke-dasharray="${s.toFixed(1)}"
                        stroke-dashoffset="${r.toFixed(1)}"
                        transform="rotate(-90 28 28)" />
                <text x="28" y="32" text-anchor="middle"
                      fill="${t}" font-size="13" font-weight="800"
                      font-family="'Segoe UI','Roboto',sans-serif"
                      style="paint-order:stroke;stroke:rgba(0,0,0,0.45);stroke-width:0.5px;">
                    ${null!=e?Math.round(i)+"%":"—"}
                </text>
            </svg>
        `}_renderBatteryGlyph(e,t,i){const s=null!=e?Math.max(0,Math.min(100,e)):0,r=Math.max(2,s/100*52),a=i?"socPulse 2s ease-in-out infinite":"none";return W`
            <svg viewBox="0 0 44 76" width="40" height="69">
                <rect x="14" y="0" width="16" height="5" rx="2" fill="rgba(255,255,255,0.15)"/>
                <rect x="6" y="4" width="32" height="60" rx="4"
                    fill="none" stroke="rgba(255,255,255,0.15)" stroke-width="2"/>
                <rect x="9" y="${(52-r+7).toFixed(1)}" width="26"
                    height="${r.toFixed(1)}" rx="2"
                    fill="${t}" opacity="0.78" style="animation:${a}"/>
                <text x="22" y="40" text-anchor="middle"
                    fill="white" font-size="13" font-weight="700"
                    font-family="'Segoe UI','Roboto',sans-serif" opacity="0.95">
                    ${null!=e?Math.round(s)+"%":"—"}
                </text>
            </svg>
        `}_fmtHours(e){if(null==e||!isFinite(e)||e<=0)return"—";if(e<1)return`${Math.round(60*e)} min`;const t=Math.floor(e),i=Math.round(60*(e-t));return 0===i?`${t} h`:`${t} h ${i} min`}_batteryEta(e,t,i){if(null==e||t<=0||Math.abs(i)<50)return null;if(i>50){const s=(100-e)/100*t;return{key:"until_full",text:this._fmtHours(s/(i/1e3))}}const s=e/100*t;return{key:"until_empty",text:this._fmtHours(s/(Math.abs(i)/1e3))}}_renderModeControls(e,t){const i=this._hass?.states[e];if(!i)return q;const s=this._hass?.states[t],r=i.state,a=s&&("allow_arbitrage"===r||"force_discharge"===r),o=this._t("battery_mode_hint_"+r)||"";return W`
            <div class="battery-section-controls">
                <div class="bsc-row">
                    <span class="bsc-label">${this._t("mode")}</span>
                    <select class="bsc-select" .value=${r}
                            @click=${e=>e.stopPropagation()}
                            @change=${t=>this._selectOption(e,t.target.value)}>
                        ${(i.attributes.options||[]).map(e=>W`
                            <option value=${e} ?selected=${e===r}>
                                ${this._t("battery_mode_"+e)||e}
                            </option>`)}
                    </select>
                </div>
                ${o?W`
                    <div class="bsc-hint">
                        <ha-icon icon="mdi:information-outline"></ha-icon>
                        <span>${o}</span>
                    </div>
                `:q}
                ${a?W`
                    <div class="bsc-row">
                        <span class="bsc-label">${this._t("reserve_soc")}</span>
                        <span class="bsc-stepper">
                            <button class="bsc-btn"
                                @click=${()=>this._stepNumber(t,-1)}>−</button>
                            <span class="bsc-stepval">${Math.round(parseFloat(s.state)||0)}%</span>
                            <button class="bsc-btn"
                                @click=${()=>this._stepNumber(t,1)}>+</button>
                        </span>
                    </div>
                `:q}
            </div>
        `}_renderBatterySection(e,t){const i=Ve[t%Ve.length],s=this._val(`battery_${e}_power`,0),r=this._val(`battery_${e}_soc`,null),a=(this._valStr(`battery_${e}_status`)||"idle").toLowerCase(),o=this._val(`battery_${e}_capacity_kwh`,0),n=this._batteryName(e),l="selling"===a,c=!l&&("charging"===a||s>50),d=!l&&("discharging"===a||s<-50),p=c||d||l,h=l?"selling_to_grid":c?"charging":d?"discharging":"idle",_=l?"#FCD170":c?"#f06292":d?"#4db6ac":"#999",g=null!=r&&o>0?r/100*o:null,u=this._batteryEta(r,o,s);return W`
            <div class="battery-section">
                <div class="battery-section-header">
                    <div class="battery-dot" style="background:${i}"></div>
                    <span class="battery-section-name">${n}</span>
                    <span class="battery-section-status"
                          style="color:${_}">
                        ${this._t(h)}
                    </span>
                </div>
                <div class="battery-section-body">
                    <div class="battery-section-glyph">
                        ${this._renderBatteryGlyph(r,_,p)}
                        <span class="battery-section-soc-label">SOC</span>
                    </div>
                    <div class="battery-section-metrics">
                        <div class="bs-row">
                            <span class="bs-label">${this._t("power")}</span>
                            <span class="bs-val"
                                  style="color:${s>50||s<-50?_:""}">
                                ${ge(s)}
                            </span>
                        </div>
                        ${null!=g?W`
                            <div class="bs-row">
                                <span class="bs-label">${this._t("stored")}</span>
                                <span class="bs-val">${this._fmt(g,1)} kWh</span>
                            </div>
                        `:q}
                        ${o>0?W`
                            <div class="bs-row">
                                <span class="bs-label">${this._t("capacity")}</span>
                                <span class="bs-val">${this._fmt(o,1)} kWh</span>
                            </div>
                        `:q}
                        ${u?W`
                            <div class="bs-row">
                                <span class="bs-label">${this._t(u.key)}</span>
                                <span class="bs-val">${u.text}</span>
                            </div>
                        `:q}
                    </div>
                </div>
                ${this._renderModeControls(`select.sem_battery_${e}_mode`,`number.sem_battery_${e}_reserve_soc`)}
            </div>
        `}render(){if(!this._hass||!this._config)return q;const e=this._theme(),t=2*Math.PI*42,i=t.toFixed(1),s=this._val("battery_soc",0),r=this._val("battery_power",0),a=this._val("battery_charge_power",0),o=this._val("battery_discharge_power",0),n=(this._valStr("battery_status")||"").toLowerCase(),l=this._val("battery_health_score",0),c=this._val("battery_cycles_estimated",0),d=this._val("daily_battery_charge_energy",0),p=this._val("daily_battery_discharge_energy",0),h=this._val("daily_battery_savings",0),_=this._val("monthly_battery_charge_energy",0),g=this._val("monthly_battery_discharge_energy",0),u=this._val("flow_solar_to_battery_energy",0),f=me(this._hass),m=this._hass?.states[`${this._prefix}battery_temperature`],y=m&&"unavailable"!==m.state&&"unknown"!==m.state?parseFloat(m.state):null,v="selling"===n,x=!v&&("charging"===n||a>10),b=!v&&("discharging"===n||o>10),$=this._hass?.states["sensor.sem_tariff_current_export_rate"],w=$&&"unavailable"!==$.state&&"unknown"!==$.state?parseFloat($.state):null,k="#FCD170",S=v?this._t("selling_to_grid"):x?this._t("charging"):b?this._t("discharging"):this._t("idle"),C=v?k:x?"#f06292":"#4db6ac",z=v?k:x?"#f06292":b?"#4db6ac":e.textSec||"#888",M=x||b||v?"0.5":"0.2",E=x||b||v?"socPulse 2s ease-in-out infinite":"none",D=Math.min(Math.max(s/100,0),1),F=(t*(1-D)).toFixed(1),I=d>0?Math.round(u/d*100):0,B=this._valStr("battery_session_type"),N="charge"===B||"discharge"===B,A="charge"===B,T=N?this._val("battery_session_energy",0):0,P=N?this._val("battery_session_duration",0):0,R=N?this._val("battery_session_avg_power",0):0,L=N?this._val("battery_session_solar_share",0):0,O=N?this._val("battery_session_cost",0):0,U=N?this._val("battery_session_savings",0):0,H=A?"#f06292":"#4db6ac";e.dotColor;const j=e.surface||"rgba(255,255,255,0.06)",G=e.surfaceBorder||"rgba(255,255,255,0.05)",K=e.surfaceHover||"rgba(255,255,255,0.12)",V=e.textSec||"#999",Y=e.textTertiary||"#888";return W`
            <style>
                :host { display: block; contain: layout style paint; }
                .wrap {
                    padding: 16px 20px;
                    position: relative;
                    background: ${ye(e,pe.battery)};
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${e.text||"#e0e0e0"});
                }
                .glow-svg { position: absolute; width: 0; height: 0; }
                .hero { display: flex; align-items: center; gap: 20px; }
                @media (max-width: 400px) { .hero { flex-direction: column; gap: 12px; } }
                .battery-ring { position: relative; width: 100px; height: 100px; flex-shrink: 0; }
                .battery-ring svg { width: 100%; height: 100%; transform: rotate(-90deg); }
                .ring-bg { fill: none; stroke: rgba(77,182,172,0.12); stroke-width: 5; }
                .soc-arc {
                    fill: none; stroke-width: 5; stroke-linecap: round;
                    transition: stroke-dashoffset 1.5s cubic-bezier(0.4,0,0.2,1);
                    filter: url(#batt-glow);
                }
                .glow-ring {
                    fill: none; stroke-width: 8; opacity: 0.2;
                    filter: url(#batt-glow-soft);
                    animation: glowPulse 3s ease-in-out infinite;
                }
                @keyframes glowPulse { 0%,100% { opacity: 0.2; } 50% { opacity: 0.08; } }
                @keyframes socPulse  { 0%,100% { opacity: 1; }   50% { opacity: 0.6; } }
                .ring-center {
                    position: absolute; top: 50%; left: 50%;
                    transform: translate(-50%, -50%);
                    text-align: center; pointer-events: none;
                }
                .battery-icon { display: block; margin: 0 auto 1px; }
                .soc-value {
                    font-size: 14px; font-weight: 700;
                    font-variant-numeric: tabular-nums;
                    text-shadow: 0 0 8px rgba(77,182,172,0.3); line-height: 1;
                }
                .metrics-col { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
                .metric-row {
                    display: flex; justify-content: space-between; align-items: baseline; padding: 2px 0; gap: 8px;
                }
                .metric-label { font-size: 12px; color: var(--secondary-text-color, ${V}); font-weight: 500; }
                .metric-val { font-size: 13px; font-weight: 600; font-variant-numeric: tabular-nums; color: #4db6ac; }
                .chips { display: flex; gap: 8px; margin-top: 14px; flex-wrap: wrap; }
                .chip {
                    flex: 1; min-width: 80px;
                    background: var(--secondary-background-color, ${j});
                    border: 1px solid var(--divider-color, ${G});
                    border-radius: 10px; padding: 8px 10px; text-align: center;
                    transition: border-color 0.3s cubic-bezier(0.4,0,0.2,1);
                }
                .chip:hover { border-color: var(--divider-color, ${K}); }
                .chip-label {
                    font-size: 11px; color: var(--secondary-text-color, ${Y});
                    font-weight: 500; letter-spacing: 0.3px; margin-bottom: 3px;
                }
                .chip-value { font-size: 13px; font-weight: 600; font-variant-numeric: tabular-nums; }
                .c-charge { color: #f06292; }
                .c-discharge { color: #4db6ac; }
                .c-savings { color: #8DC892; }
                .chip-src { font-size: 10px; color: var(--secondary-text-color, ${Y}); margin-top: 1px; }
                .session-section {
                    margin-top: 14px; padding: 10px 12px;
                    background: var(--secondary-background-color, ${j});
                    border: 1px solid var(--divider-color, ${G});
                    border-radius: 10px;
                }
                .sess-header { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
                .sess-title {
                    font-size: 12px; font-weight: 600;
                    text-transform: uppercase; letter-spacing: 0.5px;
                }
                .sess-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 4px; }
                .sess-item-label { font-size: 11px; color: var(--secondary-text-color, ${Y}); }
                .sess-item-value {
                    font-size: 12px; font-weight: 600; font-variant-numeric: tabular-nums;
                    color: var(--primary-text-color, ${e.text||"#e0e0e0"});
                }
                .monthly-section { display: flex; gap: 8px; margin-top: 10px; }

                /* ── Per-battery sections (Phase B). Same structural
                       shape as the EV card's per-charger sections so
                       a user who already knows the EV tab reads the
                       battery tab without re-learning the layout. ── */
                .battery-sections {
                    margin-top: 16px;
                    display: flex; flex-direction: column;
                    gap: 12px;
                }
                .battery-section {
                    background: ${j};
                    border: 1px solid ${G};
                    border-radius: 12px;
                    padding: 12px 14px;
                }
                .battery-section-header {
                    display: flex; align-items: center; gap: 8px;
                    margin-bottom: 10px;
                }
                .battery-dot {
                    width: 8px; height: 8px;
                    border-radius: 50%;
                    flex-shrink: 0;
                }
                .battery-section-name {
                    flex: 1; font-weight: 600; font-size: 0.95em;
                    color: var(--primary-text-color, ${e.text||"#e0e0e0"});
                }
                .battery-section-status {
                    font-size: 0.8em; font-weight: 500;
                    text-transform: uppercase; letter-spacing: 0.05em;
                }
                .battery-section-body {
                    display: flex; align-items: center; gap: 12px;
                }
                .battery-section-ring {
                    flex-shrink: 0; width: 56px; text-align: center;
                }
                .battery-section-glyph {
                    flex-shrink: 0; width: 44px; text-align: center;
                }
                .battery-section-soc-label {
                    display: block;
                    font-size: 10px; color: ${V};
                    margin-top: 2px;
                    text-transform: uppercase; letter-spacing: 0.05em;
                }
                .battery-section-metrics {
                    flex: 1;
                    display: flex; flex-direction: column; gap: 2px;
                }
                .bs-row {
                    display: flex; justify-content: space-between; align-items: baseline;
                    padding: 2px 0;
                }
                .bs-label {
                    font-size: 11px; color: ${V};
                    font-weight: 500;
                }
                .bs-val {
                    font-size: 12px; font-weight: 600;
                    color: var(--primary-text-color, ${e.text||"#e0e0e0"});
                    font-variant-numeric: tabular-nums;
                }
                /* Per-battery controls (#523) — mode select + reserve stepper */
                .battery-section-controls {
                    margin-top: 10px; padding-top: 10px;
                    border-top: 1px solid ${G};
                    display: flex; flex-direction: column; gap: 8px;
                }
                .bsc-row {
                    display: flex; align-items: center; justify-content: space-between;
                    gap: 8px;
                }
                .bsc-hint {
                    display: flex; align-items: flex-start; gap: 5px;
                    font-size: 11px; line-height: 1.35;
                    color: ${V};
                    margin: -2px 0 1px 0;
                    opacity: 0.92;
                }
                .bsc-hint ha-icon {
                    --mdc-icon-size: 13px;
                    flex: 0 0 auto; margin-top: 1px; opacity: 0.8;
                }
                .bsc-label {
                    font-size: 12px; color: ${V}; font-weight: 500;
                }
                .bsc-select {
                    background: ${j};
                    color: var(--primary-text-color, ${e.text||"#e0e0e0"});
                    border: 1px solid ${G};
                    border-radius: 8px; padding: 5px 8px; font-size: 12px;
                    font-weight: 600; cursor: pointer; min-width: 150px;
                }
                .bsc-stepper { display: flex; align-items: center; gap: 8px; }
                .bsc-btn {
                    width: 24px; height: 24px; border-radius: 6px;
                    background: ${j}; border: 1px solid ${G};
                    color: var(--primary-text-color, ${e.text||"#e0e0e0"});
                    font-size: 15px; font-weight: 700; cursor: pointer; line-height: 1;
                }
                .bsc-btn:hover { border-color: ${K}; }
                .bsc-stepval {
                    min-width: 38px; text-align: center; font-size: 13px;
                    font-weight: 700; font-variant-numeric: tabular-nums;
                    color: var(--primary-text-color, ${e.text||"#e0e0e0"});
                }
                /* Phase B mobile breakpoint — single column from the
                   ring + metrics layout collapses to stacked at
                   < 480 px (mirrors the sem-solar-card pattern). */
                @media (max-width: 480px) {
                    .battery-section-body {
                        flex-direction: column;
                        align-items: stretch;
                    }
                    .battery-section-ring { margin: 0 auto; }
                    .battery-section-glyph { margin: 0 auto; }
                }
                .month-chip {
                    flex: 1; text-align: center; padding: 6px 8px;
                    background: var(--secondary-background-color, ${j});
                    border: 1px solid var(--divider-color, ${G});
                    border-radius: 8px;
                }
            </style>

            <svg class="glow-svg">
                <defs>
                    <filter id="batt-glow" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="4" result="blur"/>
                        <feFlood flood-color="${C}" flood-opacity="0.25" result="color"/>
                        <feComposite in="color" in2="blur" operator="in" result="glow"/>
                        <feMerge><feMergeNode in="glow"/><feMergeNode in="SourceGraphic"/></feMerge>
                    </filter>
                    <filter id="batt-glow-soft" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="6" result="blur"/>
                        <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
                    </filter>
                </defs>
            </svg>

            <ha-card>
                <div class="wrap">
                    <div class="hero">
                        <div class="battery-ring">
                            <svg viewBox="0 0 100 100">
                                <circle class="glow-ring" cx="50" cy="50" r="42"
                                    style="stroke:${C};opacity:${M}"/>
                                <circle class="ring-bg" cx="50" cy="50" r="42"/>
                                <circle class="soc-arc" cx="50" cy="50" r="42"
                                    stroke-dasharray="${i}"
                                    style="stroke-dashoffset:${F};stroke:${C};animation:${E}"/>
                            </svg>
                            <div class="ring-center">
                                <!-- #523/#524 follow-up: filled SOC-level
                                     battery glyph matching the system card
                                     (was a flat outline). Fills bottom-up to
                                     SOC, tints with the arc colour, and shows a
                                     charging bolt. -->
                                <svg class="battery-icon" width="18" height="26" viewBox="0 0 20 30">
                                    <rect x="6" y="0" width="8" height="4" rx="1.5"
                                        fill="${C}" opacity="0.7"/>
                                    <rect x="2" y="4" width="16" height="26" rx="3"
                                        fill="rgba(0,0,0,0.30)" stroke="${C}"
                                        stroke-width="1.6" opacity="0.9"/>
                                    <rect x="4" y="${(28-22*D).toFixed(1)}" width="12"
                                        height="${(22*D).toFixed(1)}" rx="1.5"
                                        fill="${C}" opacity="0.55"/>
                                    <path d="M11,9.5 L6.5,18.5 L9.5,18.5 L8.5,24.5 L13.5,15 L10.5,15 Z"
                                        fill="#FCD170" opacity="${x?.95:0}"/>
                                </svg>
                                <div class="soc-value" style="color:${C}">
                                    ${s.toFixed(0)}%
                                </div>
                            </div>
                        </div>

                        <div class="metrics-col">
                            <div class="metric-row">
                                <span class="metric-label">${this._t("soc")}</span>
                                <span class="metric-val">${this._fmt(s,1)}%</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("power")}</span>
                                <span class="metric-val">${ge(r)}</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("status")}</span>
                                <span class="metric-val" style="color:${z}">${S}</span>
                            </div>
                            ${v&&null!=w?W`
                            <div class="metric-row">
                                <span class="metric-label">${this._t("export_rate")}</span>
                                <span class="metric-val" style="color:${k}">${this._fmt(w,3)} ${f}/kWh</span>
                            </div>
                            `:q}
                            <div class="metric-row">
                                <span class="metric-label">${this._t("health")}</span>
                                <span class="metric-val">${this._fmt(l,1)}%</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("cycles")}</span>
                                <span class="metric-val">${this._fmt(c,1)}</span>
                            </div>
                            ${this._batteries.length>1?"":W`
                                <div class="metric-row">
                                    <span class="metric-label">${this._t("temperature")}</span>
                                    <span class="metric-val">
                                        ${null!=y?`${this._fmt(y,1)} °C`:"—"}
                                    </span>
                                </div>
                            `}
                            <!-- #404: On multi-battery installs (length > 1)
                                 the fleet-tile temperature is hidden because
                                 each battery has its own temperature shown in
                                 its per-battery section. Per RienduPre's UX
                                 confirmation 2026-06-04. Single-battery
                                 installs (today's PROD majority) unchanged. -->
                        </div>
                    </div>

                    ${this._batteries.length>=1?W`
                        <div class="battery-sections">
                            ${this._batteries.map((e,t)=>this._renderBatterySection(e,t))}
                        </div>
                    `:W`
                        <!-- Single-battery install (#523): global mode control
                             on the hero, no per-battery section. -->
                        ${this._renderModeControls("select.sem_battery_mode","number.sem_battery_reserve_soc")}
                    `}

                    <div class="session-section">
                        <div class="sess-header">
                            <ha-icon icon="mdi:battery-sync"
                                style="--mdc-icon-size:14px;color:${N?H:e.textSec}">
                            </ha-icon>
                            <span class="sess-title" style="color:${N?H:e.textSec}">
                                ${this._t("current_session")}
                            </span>
                        </div>
                        ${N?W`
                        <div class="sess-grid">
                            <div>
                                <div class="sess-item-label">${this._t("energy")}</div>
                                <div class="sess-item-value">${this._fmt(T,2)} kWh</div>
                            </div>
                            <div>
                                <div class="sess-item-label">${this._t("duration")}</div>
                                <div class="sess-item-value">${this._fmtDuration(P)}</div>
                            </div>
                            <div>
                                <div class="sess-item-label">${this._t("avg_power")}</div>
                                <div class="sess-item-value">${ge(R)}</div>
                            </div>
                            <div>
                                <div class="sess-item-label">${this._t("source")}</div>
                                <div class="sess-item-value">
                                    ${A?`${this._t("solar")}: ${this._fmt(L,0)}%`:""}
                                </div>
                            </div>
                            <div>
                                <div class="sess-item-label">${this._t("cost")}</div>
                                <div class="sess-item-value">
                                    ${A?`${this._fmt(O,2)} ${f}`:`${this._t("saved")} ${this._fmt(U,2)} ${f}`}
                                </div>
                            </div>
                        </div>
                        `:W``}
                    </div>

                    <div class="chips">
                        <div class="chip">
                            <div class="chip-label">${this._t("charge_today")}</div>
                            <div class="chip-value c-charge">${this._fmt(d,2)} kWh</div>
                            <div class="chip-src">
                                ${I>0?`${I}% ${this._t("solar")}`:""}
                            </div>
                        </div>
                        <div class="chip">
                            <div class="chip-label">${this._t("discharge_today")}</div>
                            <div class="chip-value c-discharge">${this._fmt(p,2)} kWh</div>
                        </div>
                        <div class="chip">
                            <div class="chip-label">${this._t("savings_today")}</div>
                            <div class="chip-value c-savings">
                                ${this._fmt(h,2)} ${f}
                            </div>
                        </div>
                    </div>

                    <div class="monthly-section">
                        <div class="month-chip">
                            <div class="chip-label">
                                ${this._t("monthly")} ${this._t("charge")}
                            </div>
                            <div class="chip-value c-charge">${this._fmt(_,1)} kWh</div>
                        </div>
                        <div class="month-chip">
                            <div class="chip-label">
                                ${this._t("monthly")} ${this._t("discharge")}
                            </div>
                            <div class="chip-value c-discharge">${this._fmt(g,1)} kWh</div>
                        </div>
                    </div>
                </div>
            </ha-card>
        `}getCardSize(){return 3}static getStubConfig(){return{}}},{type:"sem-battery-card",name:"SEM Battery",description:"Lumina-styled battery hero card with SOC arc ring and key metrics"});const Ye="sensor.sem_",Xe=["grid_power","grid_import_power","grid_export_power","grid_status","daily_grid_import_energy","daily_grid_export_energy","monthly_grid_import_energy","monthly_grid_export_energy","consecutive_peak_15min","monthly_consecutive_peak","current_vs_peak_percentage","target_peak_limit","peak_margin","peak_trend","load_management_status","loads_currently_shed","available_load_reduction","controllable_devices_count","tariff_current_import_rate","tariff_current_export_rate","tariff_price_level","tariff_today_min_price","tariff_today_max_price","surplus_total_w","surplus_unallocated_w","surplus_active_devices","surplus_total_devices"];$e("sem-grid-card",class extends ke{static get watchedEntities(){return Xe.map(e=>`${Ye}${e}`)}setConfig(e){super.setConfig(e),this._prefix=e.entity_prefix||Ye}set hass(e){this._hass=e;const t=e?.language,i="function"==typeof semLocalize;let s=!1;if((t!==this._lang||i&&!this._localizeReady)&&(this._lang=t,this._localizeReady=i,s=!0),this._isFrozen()&&!s)return;const r=Xe.map(t=>e?.states[`${this._prefix}${t}`]?.state||"").join(",")+"|"+t;(r!==this._lastGridKey||s)&&(this._lastGridKey=r,this._scheduleUpdate())}get hass(){return this._hass}_val(e,t=0){return this._state(`${this._prefix}${e}`,t)}_valStr(e){return this._stateStr(`${this._prefix}${e}`)}_fmt(e,t=1){return null==e||isNaN(e)?"—":e.toFixed(t)}_peakColor(e){return e>=90?"#f06292":e>=70?"#ff9800":"#8DC892"}_priceLevelColor(e){return"high"===e?"#f06292":"low"===e?"#8DC892":"—"!==e?"#ff9800":"#888"}_metricRow(e,t){return W`
            <div class="metric-row">
                <span class="metric-label">${this._t(e)}</span>
                <span class="metric-val">${t}</span>
            </div>
        `}render(){if(!this._hass||!this._config)return q;const e=this._theme(),t=me(this._hass),i=this._val("grid_import_power"),s=this._val("grid_export_power"),r=s>i&&s>10,a=i>10,o=r?"mdi:transmission-tower-export":"mdi:transmission-tower-import",n=r?"#8353d1":"#488fc2",l=a||r?"0.45":"0.1",c=this._valStr("grid_status"),d=""!==c&&"—"!==c?this._t(c.toLowerCase()):r?this._t("exporting"):a?this._t("importing"):this._t("idle"),p=r?"#8353d1":a?"#488fc2":"#888",h=this._val("daily_grid_import_energy"),_=this._val("daily_grid_export_energy"),g=h-_,u=g<=0?"#8353d1":"#488fc2",f=this._val("current_vs_peak_percentage"),m=this._val("consecutive_peak_15min"),y=this._val("monthly_consecutive_peak"),v=this._val("target_peak_limit"),x=this._val("peak_margin"),b=this._valStr("peak_trend"),$=this._peakColor(f),w=x>0?"#8DC892":"#f06292",k=(200*Math.min(Math.max(f/100,0),1)).toFixed(1),S=this._valStr("load_management_status"),C=this._val("loads_currently_shed"),z=this._val("available_load_reduction"),M=this._val("controllable_devices_count"),E=this._val("tariff_current_import_rate"),D=this._val("tariff_current_export_rate"),F=this._valStr("tariff_price_level"),I=this._val("tariff_today_min_price"),B=this._val("tariff_today_max_price"),N=this._priceLevelColor(F),A=this._val("surplus_total_w"),T=this._val("surplus_unallocated_w"),P=Math.max(0,A-T),R=this._val("surplus_active_devices"),L=this._val("surplus_total_devices");e.dotColor;const O=e.textSec||"#999",U=e.surface||"rgba(255,255,255,0.06)",H=e.surfaceBorder||"rgba(255,255,255,0.12)";return W`
            <style>
                :host { display: block; }
                .wrap {
                    padding: 16px 20px;
                    position: relative;
                    background: ${ye(e,pe.inverter)};
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${e.text||"#e0e0e0"});
                }
                .glow-svg { position: absolute; width: 0; height: 0; }
                .hero { display: flex; align-items: center; gap: 16px; padding-bottom: 8px; }
                @media (max-width: 400px) { .hero { flex-direction: column; gap: 10px; } }
                .grid-icon-area { position: relative; width: 80px; height: 80px; flex-shrink: 0; }
                .grid-icon-area svg { width: 100%; height: 100%; }
                .grid-glow-ring {
                    fill: none; stroke-width: 6;
                    filter: url(#grid-glow-soft);
                    transition: stroke 0.4s ease, opacity 0.4s ease;
                }
                .ring-bg { fill: none; stroke: rgba(72,143,194,0.12); stroke-width: 3; }
                .ring-fill { fill: rgba(72,143,194,0.06); }
                .hero-info { flex: 1; min-width: 0; }
                .hero-power-row { display: flex; gap: 14px; margin-bottom: 4px; flex-wrap: wrap; }
                .hero-pw { display: flex; flex-direction: column; }
                .hero-pw-label {
                    font-size: 12px; text-transform: uppercase; letter-spacing: 0.4px;
                    color: var(--secondary-text-color, ${O}); margin-bottom: 1px;
                }
                .hero-pw-val { font-size: 17px; font-weight: 700; font-variant-numeric: tabular-nums; }
                .hero-pw-val.import { color: #488fc2; }
                .hero-pw-val.export { color: #8353d1; }
                .hero-status {
                    font-size: 12px; font-weight: 500;
                    text-transform: uppercase; letter-spacing: 0.5px;
                }
                .section {
                    margin-top: 10px; padding: 10px 12px;
                    background: var(--secondary-background-color, ${U});
                    border: 1px solid var(--divider-color, ${H});
                    border-radius: 10px;
                }
                .section-title {
                    font-size: 12px; font-weight: 600; text-transform: uppercase;
                    letter-spacing: 0.6px; margin-bottom: 6px;
                }
                .metric-row {
                    display: flex; justify-content: space-between; align-items: baseline; padding: 2px 0;
                }
                .metric-label {
                    font-size: 12px; color: var(--secondary-text-color, ${O}); font-weight: 500;
                }
                .metric-val {
                    font-size: 12px; font-weight: 600; font-variant-numeric: tabular-nums;
                    color: var(--primary-text-color, ${e.text||"#e0e0e0"});
                }
                .net-row {
                    margin-top: 4px; padding-top: 4px;
                    border-top: 1px solid var(--divider-color, ${H});
                }
                .peak-bar-wrap { margin: 6px 0 4px; position: relative; }
                .peak-bar-bg { width: 100%; height: 8px; fill: rgba(72,143,194,0.12); }
                .peak-bar-fill {
                    height: 8px;
                    transition: width 0.8s cubic-bezier(0.4,0,0.2,1), fill 0.4s ease;
                }
                .peak-bar-svg { width: 100%; height: 8px; display: block; }
                .peak-pct-label {
                    font-size: 12px; font-weight: 700; font-variant-numeric: tabular-nums;
                    margin-top: 2px; text-align: right;
                }
                .c-import { color: #488fc2; }
                .c-export { color: #8353d1; }
                .c-green  { color: #8DC892; }
                .c-solar  { color: #ff9800; }
            </style>

            <svg class="glow-svg">
                <defs>
                    <filter id="grid-glow" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="4" result="blur"/>
                        <feFlood flood-color="#488fc2" flood-opacity="0.3" result="color"/>
                        <feComposite in="color" in2="blur" operator="in" result="glow"/>
                        <feMerge><feMergeNode in="glow"/><feMergeNode in="SourceGraphic"/></feMerge>
                    </filter>
                    <filter id="grid-glow-soft" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="6" result="blur"/>
                        <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
                    </filter>
                </defs>
            </svg>

            <ha-card>
                <div class="wrap">
                    <!-- Hero -->
                    <div class="hero">
                        <div class="grid-icon-area">
                            <svg viewBox="0 0 80 80">
                                <circle class="grid-glow-ring" cx="40" cy="40" r="34"
                                    style="stroke:${n};opacity:${l}"/>
                                <circle class="ring-bg" cx="40" cy="40" r="34"/>
                                <circle class="ring-fill" cx="40" cy="40" r="31"/>
                                <foreignObject x="14" y="14" width="52" height="52">
                                    <div xmlns="http://www.w3.org/1999/xhtml"
                                        style="width:52px;height:52px;display:flex;align-items:center;justify-content:center">
                                        <ha-icon icon="${o}"
                                            style="--mdc-icon-size:28px;color:${n}">
                                        </ha-icon>
                                    </div>
                                </foreignObject>
                            </svg>
                        </div>

                        <div class="hero-info">
                            <div class="hero-power-row">
                                <div class="hero-pw">
                                    <span class="hero-pw-label">${this._t("import")}</span>
                                    <span class="hero-pw-val import">
                                        ${a?ge(i):"—"}
                                    </span>
                                </div>
                                <div class="hero-pw">
                                    <span class="hero-pw-label">${this._t("export")}</span>
                                    <span class="hero-pw-val export">
                                        ${r?ge(s):"—"}
                                    </span>
                                </div>
                            </div>
                            <div class="hero-status" style="color:${p}">${d}</div>
                        </div>
                    </div>

                    <!-- Today -->
                    <div class="section">
                        <div class="section-title" style="color:#488fc2">${this._t("today")}</div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("import")}</span>
                            <span class="metric-val c-import">${this._fmt(h,2)} kWh</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("export")}</span>
                            <span class="metric-val c-export">${this._fmt(_,2)} kWh</span>
                        </div>
                        <div class="metric-row net-row">
                            <span class="metric-label"><strong>${this._t(g<=0?"net_export":"net_import")}</strong></span>
                            <span class="metric-val" style="color:${u}">
                                ${this._fmt(Math.abs(g),2)} kWh
                            </span>
                        </div>
                    </div>

                    <!-- Peak Management -->
                    <div class="section">
                        <div class="section-title" style="color:#488fc2">${this._t("peak_management")}</div>
                        <div class="peak-bar-wrap">
                            <svg class="peak-bar-svg" viewBox="0 0 200 8" preserveAspectRatio="none">
                                <rect class="peak-bar-bg" x="0" y="0" width="200" height="8" rx="4" ry="4"/>
                                <rect class="peak-bar-fill" x="0" y="0"
                                    width="${k}" height="8" rx="4" ry="4"
                                    fill="${$}"/>
                            </svg>
                        </div>
                        <div class="peak-pct-label" style="color:${$}">
                            ${this._fmt(f,0)}%
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("peak_15min")}</span>
                            <span class="metric-val">${ge(m)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("monthly_peak")}</span>
                            <span class="metric-val">${ge(y)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("peak_limit")}</span>
                            <span class="metric-val">${ge(v)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("peak_margin")}</span>
                            <span class="metric-val" style="color:${w}">
                                ${ge(x)}
                            </span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("trend")}</span>
                            <span class="metric-val">${b?this._t(b):"—"}</span>
                        </div>
                    </div>

                    <!-- Load Control -->
                    <div class="section">
                        <div class="section-title" style="color:#488fc2">${this._t("load_control")}</div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("status")}</span>
                            <span class="metric-val">${S?this._t(S):"—"}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("loads_shed")}</span>
                            <span class="metric-val">${this._fmt(C,0)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("available_reduction")}</span>
                            <span class="metric-val">${ge(z)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("controllable_devices")}</span>
                            <span class="metric-val">${this._fmt(M,0)}</span>
                        </div>
                    </div>

                    <!-- Tariff -->
                    <div class="section">
                        <div class="section-title" style="color:#488fc2">${this._t("tariff")}</div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("import_rate")}</span>
                            <span class="metric-val c-import">
                                ${0!==E?`${this._fmt(E,4)} ${t}/kWh`:"—"}
                            </span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("export_rate")}</span>
                            <span class="metric-val c-export">
                                ${0!==D?`${this._fmt(D,4)} ${t}/kWh`:"—"}
                            </span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("price_level")}</span>
                            <span class="metric-val" style="color:${N}">
                                ${F?this._t(F):"—"}
                            </span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("today_min")}</span>
                            <span class="metric-val c-green">
                                ${0!==I?this._fmt(I,4):"—"}
                            </span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("today_max")}</span>
                            <span class="metric-val c-solar">
                                ${0!==B?this._fmt(B,4):"—"}
                            </span>
                        </div>
                    </div>

                    <!-- Surplus -->
                    <div class="section">
                        <div class="section-title" style="color:#488fc2">${this._t("surplus")}</div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("total_surplus")}</span>
                            <span class="metric-val c-solar">${ge(A)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("allocated")}</span>
                            <span class="metric-val">${ge(P)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("unallocated")}</span>
                            <span class="metric-val c-green">${ge(T)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("active_devices")}</span>
                            <span class="metric-val">
                                ${Math.round(R)} / ${Math.round(L)}
                            </span>
                        </div>
                    </div>
                </div>
            </ha-card>
        `}getCardSize(){return 5}static getStubConfig(){return{entity_prefix:Ye}}},{type:"sem-grid-card",name:"SEM Grid",description:"Consolidated grid card with import/export, peak management, load control, tariff, and surplus"});const Ze="sensor.sem_",Je=20;function Qe(e){return 36+556*e}function et(e){if(!e||"string"!=typeof e)return null;const t=e.match(/^(\d{1,2}):(\d{2})$/);if(!t)return null;const i=parseInt(t[1],10),s=parseInt(t[2],10);return i>24||s>59?null:(i+s/60)/24}function tt(e){if(!Array.isArray(e))return[];const t=[];let i=-1;for(let s=0;s<24;s++)e[s]&&-1===i?i=s:e[s]||-1===i||(t.push({start:i/24,end:s/24}),i=-1);return-1!==i&&t.push({start:i/24,end:1}),t}$e("sem-schedule-card",class extends ke{static get watchedEntities(){return[`${Ze}tariff_current_import_rate`,`${Ze}tariff_price_level`,`${Ze}night_start_time`,`${Ze}night_end_time`,`${Ze}best_surplus_window`,`${Ze}predicted_surplus_window`,`${Ze}ev_power`,`${Ze}charging_state`,`${Ze}surplus_total_w`]}setConfig(e){super.setConfig(e),this._prefix=e.entity_prefix||Ze}set hass(e){this._hass=e;const t=e?.language,i="function"==typeof semLocalize;let s=!1;if((t!==this._lang||i&&!this._localizeReady)&&(this._lang=t,this._localizeReady=i,s=!0),this._isFrozen()&&!s)return;const r=["tariff_current_import_rate","tariff_price_level","night_start_time","night_end_time","best_surplus_window","predicted_surplus_window","ev_power","charging_state"].map(t=>{const i=e?.states[`${this._prefix}${t}`];return(i?.state||"")+JSON.stringify(i?.attributes?.schedule_today||"")+JSON.stringify(i?.attributes?.tariff_schedule_today||"")+JSON.stringify(i?.attributes?.schedule_surplus_hours||"")+JSON.stringify(i?.attributes?.schedule_ev_hours||"")}),a=r.join("|")+"|"+t;(a!==this._lastSchedKey||s)&&(this._lastSchedKey=a,this._scheduleUpdate())}get hass(){return this._hass}_stateObj(e){return this._hass?.states[`${this._prefix}${e}`]||null}_getTariffSchedule(){const e=this._stateObj("tariff_current_import_rate")||this._stateObj("tariff_price_level"),t=e?.attributes?.schedule_today||e?.attributes?.tariff_schedule_today;if(Array.isArray(t)&&t.length>0)return t.map(e=>({start:et(e.start)??0,end:et(e.end)??1,level:e.level||("NT"===(e.tariff||e.type||"HT").toUpperCase()?"cheap":"normal"),type:(e.tariff||e.type||"HT").toUpperCase(),avgPrice:e.avg_price}));const i=this._stateObj("tariff_price_level")?.state,s=new Set(["cheap","very_cheap","normal","expensive","very_expensive"]);return i&&s.has(i)?[{start:0,end:1,level:i,type:"cheap"===i||"very_cheap"===i?"NT":"HT",isFallback:!0}]:[{start:0,end:1,level:"normal",type:"HT",isFallback:!0}]}_getNightWindow(){const e=et(this._stateObj("night_start_time")?.state),t=et(this._stateObj("night_end_time")?.state);return null==e||null==t?null:{start:e,end:t}}_getPredictedSurplusWindow(){for(const e of["predicted_surplus_window","best_surplus_window"]){const t=this._stateObj(e)?.state;if(!t||"unknown"===t||"unavailable"===t)continue;if(t.toLowerCase().startsWith("tomorrow"))continue;const i=t.split(/[-–]/);if(2!==i.length)continue;const s=et(i[0].trim()),r=et(i[1].trim());if(null!=s&&null!=r)return{start:s,end:r}}return null}_getSurplusBlocks(){const e=this._hass?.states[`${this._prefix}surplus_total_w`];return tt(e?.attributes?.schedule_surplus_hours)}_getEvBlocks(){const e=this._hass?.states[`${this._prefix}surplus_total_w`];return tt(e?.attributes?.schedule_ev_hours)}_getEvPlanWindow(){const e=this._stateObj("charging_state"),t=e?.attributes?.today_plan;if(!Array.isArray(t))return null;const i=new Date;i.setHours(0,0,0,0);const s=i.getTime()+864e5,r=e=>{const t=new Date(e).getTime();return t<i.getTime()||t>=s?null:(t-i.getTime())/864e5};let a,o,n,l;for(const e of t)"ev_charge_start"===e.kind?a=r(e.when):"ev_min_reached"===e.kind?(o=r(e.when),l=e.values?.kwh):"ev_deadline"===e.kind&&(n=r(e.when));const c=o??n;return null==a&&null==c&&null==n?null:{plan:null!=a&&null!=c&&c>a?[{start:a,end:c,kwh:l}]:[],deadlineFrac:n,minReachedFrac:o}}_getSolarIntensity(){const e=this._stateObj("forecast_peak_time_today")?.state||this._stateObj("peak_time_today")?.state,t=parseFloat(this._stateObj("forecast_today_kwh")?.state||this._stateObj("forecast_today")?.state);if(!e||isNaN(t)||t<.5)return null;const i=et(e.slice(0,5));if(null==i)return null;const s=new Array(24).fill(0);for(let e=0;e<24;e++){const t=e/24-i,r=Math.exp(-t*t/(.26*.13));s[e]=r}const r=Math.max(...s);return s.map(e=>e/r)}_isEvCharging(){const e=parseFloat(this._stateObj("ev_power")?.state);if(!isNaN(e)&&e>10)return!0;const t=this._stateObj("charging_state")?.state;return t&&"charging"===t.toLowerCase()}_getNowBadges(){const e=this._stateObj("tariff_price_level")?.state,t=["cheap","normal","expensive","very_cheap","very_expensive"].includes(e)?e:null,i=["active","target_reached"].includes(this._stateObj("night_charging_status")?.state),s=parseFloat(this._stateObj("solar_power")?.state),r=!isNaN(s)&&s>50?`${(s/1e3).toFixed(1)} kW`:null,a=this._isEvCharging(),o=this._getEvPlanWindow();return{tariff:t,night:i?"now":null,surplus:r,ev:a?"charging":o?.plan?.length?"planned":null}}_buildSvgContent(e){const t=pe,i=e.textSec||"#888",s=e.textTertiary||"#777",r=e.surface||"rgba(255,255,255,0.03)";let a="";for(let e=0;e<=24;e+=2){const t=Qe(e/24);a+=`<text x="${t}" y="12" text-anchor="middle" fill="${i}"\n                font-size="10" font-family="'Segoe UI','Roboto',sans-serif"\n                font-variant-numeric="tabular-nums">${e.toString().padStart(2,"0")}</text>`}[this._t("tariff"),this._t("night"),this._t("surplus"),this._t("ev")].forEach((e,t)=>{a+=`<text x="32" y="${Je+22*t+9+3.5}" text-anchor="end" fill="${s}"\n                font-size="10" font-family="'Segoe UI','Roboto',sans-serif">${e}</text>`});for(let e=0;e<4;e++){a+=`<rect x="36" y="${Je+22*e}" width="556" height="18" rx="3" fill="${r}"/>`}const o={cheap:{fill:"#66bb6a",opacity:.62},normal:{fill:t.solar,opacity:.55},expensive:{fill:"#e91e63",opacity:.9}},n={cheap:"cheap",normal:"normal",expensive:"expensive"};for(const e of this._getTariffSchedule()){const t=Qe(e.start),i=Qe(e.end)-t,s=o[e.level]||o.normal,r=!0===e.isFallback,l=r?.35*s.opacity:s.opacity,c=r?` stroke="${s.fill}" stroke-width="1" stroke-opacity="0.6" stroke-dasharray="3,2"`:"",d=r?`${e.level} (no per-hour data — showing current level)`:null!=e.avgPrice?`${e.level} · avg ${e.avgPrice.toFixed(2)}`:e.level;if(a+=`<rect x="${t}" y="20" width="${i}" height="18"\n                rx="3" fill="${s.fill}" opacity="${l}"${c}>\n                <title>${d}</title></rect>`,i>30){const s=e.level&&n[e.level]?n[e.level]:e.type.toLowerCase();a+=`<text x="${t+i/2}" y="32.5" text-anchor="middle"\n                    fill="rgba(255,255,255,0.92)" font-size="9" font-weight="600"\n                    font-family="'Segoe UI','Roboto',sans-serif">${this._t(s)}</text>`}}const l=this._getNightWindow();if(l){const e=e=>{const t=Math.round(24*e*60);return`${String(Math.floor(t/60)).padStart(2,"0")}:${String(t%60).padStart(2,"0")}`},t=`${this._t("night")} ${e(l.start)}–${e(l.end)}`;if(l.start>l.end){const e=Qe(l.start);a+=`<rect x="${e}" y="42" width="${Qe(1)-e}"\n                    height="18" rx="3" fill="#42a5f5" opacity="0.55"><title>${t}</title></rect>`,a+=`<rect x="${Qe(0)}" y="42"\n                    width="${Qe(l.end)-Qe(0)}" height="18"\n                    rx="3" fill="#42a5f5" opacity="0.55"><title>${t}</title></rect>`}else{const e=Qe(l.start),i=Qe(l.end)-e;a+=`<rect x="${e}" y="42" width="${i}" height="18"\n                    rx="3" fill="#42a5f5" opacity="0.55"><title>${t}</title></rect>`}}const c=this._getSolarIntensity(),d=parseFloat(this._stateObj("forecast_today_kwh")?.state||NaN);if(c){const e=isNaN(d)?this._t("surplus"):`${this._t("surplus")} · forecast ${d.toFixed(1)} kWh`;for(let t=0;t<24;t++){const i=c[t];if(i<.08)continue;const s=Qe(t/24),r=Qe(1/24);a+=`<rect x="${s}" y="64" width="${r}" height="18"\n                    fill="#fdd835" opacity="${(.55*i).toFixed(2)}"><title>${e}</title></rect>`}}const p=this._getPredictedSurplusWindow();if(p){const e=Qe(p.start),t=Math.max(0,Qe(p.end)-e);a+=`<rect x="${e}" y="64" width="${t}" height="18"\n                rx="3" fill="none" stroke="#fdd835" stroke-width="1"\n                stroke-opacity="0.5" stroke-dasharray="2,2"/>`}for(const e of this._getSurplusBlocks()){const t=Qe(e.start),i=Math.max(0,Qe(e.end)-t);a+=`<rect x="${t}" y="64" width="${i}" height="18"\n                rx="3" fill="#fdd835" opacity="0.62"/>`}const h=this._getEvPlanWindow();if(h?.plan?.length)for(const e of h.plan){const i=Qe(e.start),s=Math.max(0,Qe(e.end)-i),r=e.kwh?`${this._t("plan_ev_charge_start")} → ${this._t("plan_ev_min_reached").replace("{kwh}",e.kwh)}`:this._t("plan_ev_charge_start");a+=`<rect x="${i}" y="86" width="${s}" height="18"\n                    rx="3" fill="${t.ev}" opacity="0.30"\n                    stroke="${t.ev}" stroke-width="0.6" stroke-opacity="0.6"\n                    stroke-dasharray="3,2"><title>${r}</title></rect>`}for(const e of this._getEvBlocks()){const i=Qe(e.start),s=Math.max(0,Qe(e.end)-i);a+=`<rect x="${i}" y="86" width="${s}" height="18"\n                rx="3" fill="${t.ev}" opacity="0.55"/>`}if(null!=h?.deadlineFrac){const e=Qe(h.deadlineFrac);a+=`<line x1="${e}" y1="84" x2="${e}" y2="106"\n                stroke="#f06292" stroke-width="1.2" stroke-dasharray="2,1" opacity="0.85">\n                <title>${this._t("plan_ev_deadline")}</title></line>`}if(this._isEvCharging()){const e=new Date,i=(e.getHours()+e.getMinutes()/60)/24,s=.5/24,r=Math.max(0,i-s),o=Math.min(1,i+s),n=Qe(r),l=Qe(o)-n;a+=`<rect x="${n}" y="86" width="${l}" height="18"\n                rx="3" fill="${t.ev}" opacity="0.95"/>`}const _=new Date,g=Qe((_.getHours()+_.getMinutes()/60)/24);return a+=`<line x1="${g}" y1="18" x2="${g}" y2="104"\n            stroke="#ef5350" stroke-width="1.5" stroke-linecap="round" opacity="0.9"/>`,a+=`<polygon points="${g-3},18 ${g+3},18 ${g},22"\n            fill="#ef5350" opacity="0.9"/>`,a}render(){if(!this._hass||!this._config)return q;const e=this._theme(),t=e.dotColor||"rgba(128,128,128,0.04)",i=this._buildSvgContent(e),s=this._getNowBadges(),r={cheap:"#66bb6a",very_cheap:"#66bb6a",normal:"#ff9800",expensive:"#e91e63",very_expensive:"#e91e63",now:"#42a5f5",charging:"#8DC892",planned:"#8DC892"},a=(e,t)=>{if(!t)return q;const i=r[t]||"#888",s=/\d/.test(t)?t:this._t(t);return W`<span class="now-badge"
                style="color:${i};border-color:${i}55;background:${i}22">${s}</span>`};return W`
            <style>
                :host { display: block; }
                .wrap {
                    padding: 12px 14px 8px;
                    position: relative;
                    background:
                        radial-gradient(ellipse 70% 60% at 50% 25%, rgba(150,202,238,0.06) 0%, transparent 100%),
                        radial-gradient(circle at 2px 2px, ${t} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${e.text||"#e0e0e0"});
                }
                .timeline-svg { width: 100%; height: auto; }
                .now-row {
                    display: flex; align-items: center; gap: 10px;
                    font-size: 11px; color: var(--secondary-text-color, #999);
                    margin-top: 4px; flex-wrap: wrap;
                }
                .now-row .now-label {
                    font-weight: 600; opacity: 0.7; margin-right: 4px;
                }
                .now-row .row-pair {
                    display: inline-flex; align-items: center; gap: 4px;
                }
                .now-row .row-pair > span:first-child { opacity: 0.7; }
                .now-badge {
                    display: inline-block; padding: 1px 7px;
                    border-radius: 999px; border: 1px solid;
                    font-size: 11px; font-weight: 600;
                    text-transform: capitalize;
                }
                .legend {
                    display: flex; gap: 14px; flex-wrap: wrap;
                    margin-top: 6px; padding-top: 6px;
                    border-top: 1px dashed rgba(255,255,255,0.06);
                    font-size: 11px; color: var(--secondary-text-color, #888);
                }
                .legend .item {
                    display: inline-flex; align-items: center; gap: 4px;
                }
                .legend i {
                    width: 10px; height: 10px; border-radius: 2px;
                    display: inline-block;
                }
            </style>
            <ha-card>
                <div class="wrap">
                    <svg class="timeline-svg"
                        viewBox="0 0 ${600} ${112}"
                        preserveAspectRatio="xMidYMid meet"
                        role="img"
                        aria-label="24-hour schedule timeline"
                        .innerHTML=${i}>
                    </svg>
                    <div class="now-row" role="status">
                        <span class="now-label">${this._t("plan_now")}:</span>
                        <span class="row-pair"><span>${this._t("tariff")}</span>${a(0,s.tariff)}</span>
                        <span class="row-pair"><span>${this._t("night")}</span>${a(0,s.night)}</span>
                        <span class="row-pair"><span>${this._t("surplus")}</span>${a(0,s.surplus)}</span>
                        <span class="row-pair"><span>${this._t("ev")}</span>${a(0,s.ev)}</span>
                    </div>
                    <div class="legend">
                        <span class="item"><i style="background:#66bb6a"></i>${this._t("cheap")}</span>
                        <span class="item"><i style="background:${pe.solar}"></i>${this._t("normal")}</span>
                        <span class="item"><i style="background:#e91e63"></i>${this._t("expensive")}</span>
                        <span class="item"><i style="background:#42a5f5"></i>${this._t("night")}</span>
                        <span class="item"><i style="background:#fdd835"></i>${this._t("surplus")}</span>
                        <span class="item"><i style="background:${pe.ev}"></i>${this._t("ev")}</span>
                    </div>
                </div>
            </ha-card>
        `}getCardSize(){return 2}static getStubConfig(){return{}}},{type:"sem-schedule-card",name:"SEM Schedule",description:"24-hour timeline showing tariff, night window, surplus window, and EV charging periods"});const it=[{id:"autostart",entity:"number.sem_battery_auto_start_soc",icon:"mdi:play-circle",labelKey:"auto_start_soc",helpKey:"zone_help_autostart",color:"#4db6ac"},{id:"buffer",entity:"number.sem_battery_buffer_soc",icon:"mdi:shield-half-full",labelKey:"buffer_soc",helpKey:"zone_help_buffer",color:"#ff9800"},{id:"priority",entity:"number.sem_battery_priority_soc",icon:"mdi:shield-alert",labelKey:"priority_soc",helpKey:"zone_help_priority",color:"#f44336"}];$e("sem-battery-zones-card",class extends ke{static get watchedEntities(){return it.map(e=>e.entity)}static get properties(){return{...super.properties,_showHelp:{state:!0}}}constructor(){super(),this._showHelp=!1}_toggleHelp(){this._showHelp=!this._showHelp}setConfig(e){super.setConfig(e)}_getDecimalsForZone(e){const t=this._hass?.states[e];return(t&&parseFloat(t.attributes.step)||1)<1?1:0}_renderZoneMarkers(e){return it.map(t=>{const i=this._state(t.entity),s=Math.max(0,Math.min(100,i));return W`
                <div class="zone-marker" style="left:${s}%">
                    <div class="zone-dot" style="background:${t.color};border-color:${e.isDark?"#1e232d":"#fff"}"></div>
                    <span class="zone-marker-label">${i.toFixed(0)}%</span>
                </div>
            `})}_renderStepper(e,t){const i=this._state(e.entity),s=this._getDecimalsForZone(e.entity),r=this._t(e.labelKey),a=this._showHelp?this._t(e.helpKey):"";return W`
            <div class="stepper-cell">
                <div class="stepper-row">
                    <ha-icon icon="${e.icon}" style="--mdc-icon-size:18px;color:${e.color}"></ha-icon>
                    <span class="stepper-label">${r}</span>
                    <div class="stepper-controls">
                        <button
                            class="stepper-minus"
                            aria-label="Decrease ${r}"
                            @click=${()=>this._stepNumber(e.entity,-1)}
                            @pointerdown=${()=>this._startHold(e.entity,-1)}
                            @pointerup=${()=>this._stopHold(e.entity)}
                            @pointerleave=${()=>this._stopHold(e.entity)}
                        >−</button>
                        <span class="stepper-value">${i.toFixed(s)}%</span>
                        <button
                            class="stepper-plus"
                            aria-label="Increase ${r}"
                            @click=${()=>this._stepNumber(e.entity,1)}
                            @pointerdown=${()=>this._startHold(e.entity,1)}
                            @pointerup=${()=>this._stopHold(e.entity)}
                            @pointerleave=${()=>this._stopHold(e.entity)}
                        >+</button>
                    </div>
                </div>
                ${this._showHelp?W`<div class="zone-help-text" style="border-left-color:${e.color}">${a}</div>`:q}
            </div>
        `}render(){if(!this._config)return q;const e=this._theme(),t=this._state(it[0].entity),i=this._state(it[1].entity),s=this._state(it[3].entity),r=`${this._t("auto_start_soc")} ${t.toFixed(0)}% · Buffer ${i.toFixed(0)}% · ${this._t("priority_soc")} ${s.toFixed(0)}%`;return W`
            <style>
                :host { display: block; contain: layout style paint; }
                .wrap {
                    padding: 16px;
                    background:
                        radial-gradient(ellipse 70% 60% at 50% 25%, rgba(77,182,172,0.06) 0%, transparent 100%),
                        radial-gradient(circle at 2px 2px, ${e.dotColor} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${e.text});
                }
                .header {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    margin-bottom: 12px;
                }
                .header-title {
                    font-size: 14px;
                    font-weight: 600;
                    color: #4db6ac;
                }
                .subtitle {
                    flex: 1;
                    text-align: right;
                    font-size: 12px;
                    color: var(--secondary-text-color, ${e.textSec});
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                }
                .zone-bar-wrap {
                    margin: 0 0 14px;
                    padding: 0 4px;
                }
                .zone-bar {
                    position: relative;
                    height: 8px;
                    border-radius: 4px;
                    background: linear-gradient(90deg, #f44336 0%, #ff9800 30%, #4db6ac 60%, #488fc2 80%, #8DC892 100%);
                    opacity: 0.6;
                }
                .zone-marker {
                    position: absolute;
                    top: -6px;
                    transform: translateX(-50%);
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    transition: left 0.3s ease;
                }
                .zone-dot {
                    width: 10px;
                    height: 10px;
                    border-radius: 50%;
                    border: 2px solid;
                    box-shadow: 0 0 4px rgba(0,0,0,0.3);
                }
                .zone-marker-label {
                    font-size: 10px;
                    font-weight: 600;
                    margin-top: 2px;
                    color: var(--secondary-text-color, ${e.textSec});
                    font-variant-numeric: tabular-nums;
                }
                .stepper-grid {
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                    gap: 4px 16px;
                }
                .stepper-row {
                    display: flex;
                    align-items: center;
                    gap: 6px;
                    padding: 6px 0;
                }
                .stepper-label {
                    font-size: 12px;
                    font-weight: 500;
                    flex: 1;
                    min-width: 0;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                }
                .stepper-controls {
                    display: flex;
                    align-items: center;
                    gap: 2px;
                    flex-shrink: 0;
                }
                .stepper-minus, .stepper-plus {
                    width: 28px;
                    height: 28px;
                    border-radius: 7px;
                    border: 1px solid ${e.surfaceBorder};
                    background: ${e.surface};
                    color: var(--primary-text-color, ${e.text});
                    font-size: 15px;
                    font-weight: 600;
                    cursor: pointer;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    transition: background 0.15s;
                    user-select: none;
                    -webkit-user-select: none;
                    touch-action: manipulation;
                    padding: 0;
                    line-height: 1;
                }
                .stepper-minus:hover, .stepper-plus:hover {
                    background: ${e.surfaceHover};
                }
                .stepper-value {
                    font-size: 13px;
                    font-weight: 600;
                    min-width: 48px;
                    text-align: center;
                    font-variant-numeric: tabular-nums;
                }
                /* Help toggle in header (#sem-zone-help, 2026-06-06). Tap
                   the (?) to reveal one-line descriptions under each
                   stepper. Off by default — keeps the card compact. */
                .help-toggle {
                    cursor: pointer;
                    color: var(--secondary-text-color, ${e.textSec});
                    opacity: 0.7;
                    flex-shrink: 0;
                    transition: opacity 0.15s, color 0.15s;
                    user-select: none;
                    -webkit-user-select: none;
                }
                .help-toggle:hover { opacity: 1; }
                .help-toggle.on { color: #4db6ac; opacity: 1; }
                .stepper-cell { display: flex; flex-direction: column; }
                .zone-help-text {
                    font-size: 11px;
                    line-height: 1.35;
                    color: var(--secondary-text-color, ${e.textSec});
                    opacity: 0.8;
                    padding: 4px 6px 6px 36px;
                    border-left: 2px solid;
                    margin-left: 9px;
                    margin-top: -2px;
                    margin-bottom: 4px;
                }
                @media (max-width: 480px) {
                    .stepper-grid { grid-template-columns: 1fr; }
                }
            </style>
            <div class="wrap">
                <div class="header">
                    <ha-icon icon="mdi:battery-charging-medium" style="--mdc-icon-size:18px;color:#4db6ac"></ha-icon>
                    <span class="header-title">${this._t("soc_zones")}</span>
                    <span class="subtitle">${r}</span>
                    <ha-icon
                        class="help-toggle ${this._showHelp?"on":""}"
                        icon="${this._showHelp?"mdi:help-circle":"mdi:help-circle-outline"}"
                        title="${this._t("zone_help_toggle")}"
                        @click=${()=>this._toggleHelp()}
                        style="--mdc-icon-size:18px"
                    ></ha-icon>
                </div>
                <div class="zone-bar-wrap">
                    <div class="zone-bar">
                        ${this._renderZoneMarkers(e)}
                    </div>
                </div>
                <div class="stepper-grid">
                    ${it.map(t=>this._renderStepper(t,e))}
                </div>
            </div>
        `}getCardSize(){return 4}static getStubConfig(){return{}}},{type:"custom:sem-battery-zones-card",name:"SEM Battery Zones Card",description:"SOC zone configuration for Solar Energy Management",preview:!1});const st="sensor.sem_",rt=["daily_costs","daily_savings","daily_export_revenue","daily_battery_savings","daily_net_cost","monthly_costs","monthly_savings","monthly_export_revenue","monthly_net_cost","monthly_battery_savings","yearly_costs","yearly_savings","yearly_export_revenue","yearly_net_cost","yearly_battery_savings","lifetime_total_savings","roi_percentage","roi_payback_years","roi_annual_savings","daily_co2_avoided","yearly_co2_avoided","lifetime_co2_avoided","yearly_trees_equivalent","lifetime_trees_equivalent"];$e("sem-costs-card",class extends ke{static get watchedEntities(){return rt.map(e=>`${st}${e}`)}setConfig(e){super.setConfig(e),this._prefix=e.entity_prefix||st}_val(e,t=0){const i=this._hass?.states[`${this._prefix}${e}`];return i&&"unavailable"!==i.state&&"unknown"!==i.state?parseFloat(i.state)??t:t}_fmt(e,t=2){return null==e||isNaN(e)?"—":e.toFixed(t)}_fmtCurr(e,t,i=2){return null==e||isNaN(e)?"—":e.toFixed(i)+" "+t}_netColor(e){return e<=0?"#8DC892":"#f06292"}_renderPeriodSection(e,t,i,s,r){const a=this._val(`${e}_costs`),o=this._val(`${e}_savings`),n=this._val(`${e}_battery_savings`),l=this._val(`${e}_export_revenue`),c=this._val(`${e}_net_cost`),d=this._netColor(c),p=(c<=0?"+":"")+this._fmtCurr(Math.abs(c),s);return W`
            <div class="section">
                <div class="section-title">${this._t(t)}</div>
                <div class="metric-row">
                    <span class="metric-label">${this._t("import_cost")}</span>
                    <span class="metric-val c-import">${this._fmtCurr(a,s)}</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">${this._t("solar_savings")}</span>
                    <span class="metric-val c-solar">${this._fmtCurr(o,s)}</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">${this._t("battery_savings")}</span>
                    <span class="metric-val c-battery">${this._fmtCurr(n,s)}</span>
                </div>
                <div class="metric-row">
                    <span class="metric-label">${this._t("export_revenue")}</span>
                    <span class="metric-val c-export">${this._fmtCurr(l,s)}</span>
                </div>
                <div class="metric-row net-row">
                    <span class="metric-label"><strong>${this._t(c<=0?"net_saving":"net_cost")}</strong></span>
                    <span class="metric-val" style="color:${d}">${p}</span>
                </div>
            </div>
        `}render(){if(!this._config||!this._hass)return q;const e=me(this._hass),t=this._theme(),i=this._val("daily_net_cost"),s=i<=0,r=s?"#8DC892":"#f06292",a=(s?"+":"")+this._fmt(Math.abs(i),2)+" "+e,o=s?this._t("net_saving_today"):this._t("net_cost_today"),n=this._val("roi_percentage"),l=n>=0?"#8DC892":"#f06292",c=this._val("roi_payback_years");return W`
            <ha-card>
                <div class="wrap">
                    <!-- Hero -->
                    <div class="hero">
                        <div class="hero-net" style="color:${r}">${a}</div>
                        <div class="hero-label" style="color:${r}">${o}</div>
                    </div>

                    <!-- Today / Monthly / Yearly (3 columns) -->
                    <div class="three-col">
                        ${this._renderPeriodSection("daily","today","d",e,t)}
                        ${this._renderPeriodSection("monthly","monthly","m",e,t)}
                        ${this._renderPeriodSection("yearly","yearly","y",e,t)}
                    </div>

                    <!-- ROI + Environmental (2 columns) -->
                    <div class="two-col">
                        <div class="section">
                            <div class="section-title">${this._t("roi")}</div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("lifetime_savings")}</span>
                                <span class="metric-val c-green">${this._fmtCurr(this._val("lifetime_total_savings"),e,0)}</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("annual_savings")}</span>
                                <span class="metric-val c-green">${this._fmtCurr(this._val("roi_annual_savings"),e,0)}</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("payback_years")}</span>
                                <span class="metric-val">${c>0?this._fmt(c,1)+" "+this._t("years"):"—"}</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("roi_percentage")}</span>
                                <span class="metric-val" style="color:${l}">${0!==n?this._fmt(n,1)+"%":"—"}</span>
                            </div>
                        </div>
                        <div class="section">
                            <div class="section-title">${this._t("environment")}</div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("co2_today")}</span>
                                <span class="metric-val c-leaf">${this._fmt(this._val("daily_co2_avoided"),1)} kg</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("co2_yearly")}</span>
                                <span class="metric-val c-leaf">${this._fmt(this._val("yearly_co2_avoided"),0)} kg</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("co2_lifetime")}</span>
                                <span class="metric-val c-leaf">${this._fmt(this._val("lifetime_co2_avoided"),0)} kg</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("trees_yearly")}</span>
                                <span class="metric-val c-leaf">${this._fmt(this._val("yearly_trees_equivalent"),1)}</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("trees_lifetime")}</span>
                                <span class="metric-val c-leaf">${this._fmt(this._val("lifetime_trees_equivalent"),1)}</span>
                            </div>
                        </div>
                    </div>
                </div>
            </ha-card>
        `}static get styles(){return a`
            :host { display: block; }
            .wrap {
                padding: 16px 20px;
                position: relative;
                background:
                    radial-gradient(ellipse 70% 60% at 50% 25%, rgba(240,98,146,0.06) 0%, transparent 100%),
                    radial-gradient(circle at 2px 2px, rgba(128,128,128,0.05) 0.7px, transparent 0.7px);
                background-size: 100% 100%, 50px 50px;
                font-family: 'Segoe UI','Roboto',sans-serif;
                color: var(--primary-text-color, #e0e0e0);
            }

            /* ── Hero ── */
            .hero {
                display: flex; align-items: center; justify-content: center;
                flex-direction: column; padding: 4px 0 8px;
                text-align: center;
            }
            .hero-net {
                font-size: 28px; font-weight: 700;
                font-variant-numeric: tabular-nums;
                text-shadow: 0 0 12px rgba(141,200,146,0.3);
                line-height: 1.1;
            }
            .hero-label {
                font-size: 12px; font-weight: 500; text-transform: uppercase;
                letter-spacing: 0.6px; margin-top: 2px;
                color: var(--secondary-text-color, #999);
            }

            /* ── Section ── */
            .section {
                margin-top: 10px; padding: 10px 12px;
                background: var(--secondary-background-color, rgba(255,255,255,0.06));
                border: 1px solid var(--divider-color, rgba(255,255,255,0.12));
                border-radius: 10px;
            }
            .section-title {
                font-size: 12px; font-weight: 600; text-transform: uppercase;
                letter-spacing: 0.6px; color: #8DC892; margin-bottom: 6px;
            }

            /* ── Multi-column layouts ── */
            .three-col {
                display: grid;
                grid-template-columns: 1fr 1fr 1fr;
                gap: 0 10px;
            }
            .two-col {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 0 10px;
            }
            @media (max-width: 400px) {
                .three-col { grid-template-columns: 1fr; }
                .two-col { grid-template-columns: 1fr; }
            }

            /* ── Metric rows ── */
            .metric-row {
                display: flex; justify-content: space-between; align-items: baseline;
                padding: 2px 0;
            }
            .net-row {
                margin-top: 4px; padding-top: 4px;
                border-top: 1px solid var(--divider-color, rgba(255,255,255,0.12));
            }
            .metric-label {
                font-size: 12px; color: var(--secondary-text-color, #999);
                font-weight: 500;
            }
            .metric-val {
                font-size: 12px; font-weight: 600;
                font-variant-numeric: tabular-nums;
                color: var(--primary-text-color, #e0e0e0);
            }

            /* Color helpers */
            .c-import  { color: #488fc2; }
            .c-solar   { color: #ff9800; }
            .c-battery { color: #4db6ac; }
            .c-export  { color: #8353d1; }
            .c-green   { color: #8DC892; }
            .c-leaf    { color: #8DC892; }
        `}getCardSize(){return 5}static getStubConfig(){return{entity_prefix:"sensor.sem_"}}},{type:"sem-costs-card",name:"SEM Costs",description:"Consolidated financial card with daily/monthly/yearly costs, savings, ROI, and environmental impact"});const at="sensor.sem_",ot=[{id:"ev_econ",icon:"mdi:car-electric",color:"#8DC892",titleKey:"ev_charging_economics"},{id:"investment",icon:"mdi:bank",color:"#96CAEE",titleKey:"system_investment_cost"},{id:"demand",icon:"mdi:flash-triangle",color:"#ff9800",titleKey:"demand_charge"},{id:"tariff",icon:"mdi:tag-multiple",color:"#488fc2",titleKey:"tariff_rates"}];$e("sem-costs-detail-card",class extends ke{static get watchedEntities(){return[`${at}lifetime_ev_energy`,`${at}lifetime_ev_cost`,`${at}lifetime_ev_solar_share`,"number.sem_system_investment_cost",`${at}monthly_consecutive_peak`,`${at}power_charge_cost`,"number.sem_demand_charge_rate",`${at}tariff_current_import_rate`,`${at}tariff_current_export_rate`,`${at}tariff_price_level`,"number.sem_electricity_import_rate","number.sem_electricity_export_rate"]}constructor(){super(),this._collapsed={}}setConfig(e){super.setConfig(e),this._prefix=e.entity_prefix||at}_val(e,t=0){const i=this._hass?.states[`${this._prefix}${e}`];return i&&"unavailable"!==i.state&&"unknown"!==i.state?parseFloat(i.state)??t:t}_valStr(e){const t=this._hass?.states[`${this._prefix}${e}`];return t&&"unavailable"!==t.state&&"unknown"!==t.state?t.state:""}_numVal(e,t=0){const i=this._frozenEntities[e];if(i)return i.value;const s=this._hass?.states[e];return s&&"unavailable"!==s.state&&"unknown"!==s.state?parseFloat(s.state)??t:t}_entityExists(e){const t=this._hass?.states[e];return!(!t||"unavailable"===t.state||"unknown"===t.state)}_toggleSection(e){this._collapsed={...this._collapsed,[e]:!this._collapsed[e]},this.requestUpdate()}_sectionSubtitle(e,t){if("ev_econ"===e){const e=this._val("lifetime_ev_energy");if(e<=0)return this._t("no_ev_data");const i=this._val("lifetime_ev_cost"),s=this._val("lifetime_ev_solar_share");return`${(e>0?i/e:0).toFixed(2)} ${t}/kWh · ${s.toFixed(0)}% solar`}if("investment"===e){const e=this._numVal("number.sem_system_investment_cost");return e>0?`${e.toFixed(0)} ${t}`:""}if("demand"===e){const e=this._val("monthly_consecutive_peak"),i=this._val("power_charge_cost");return`${e.toFixed(1)} kW · ${i.toFixed(2)} ${t}`}if("tariff"===e){const e=this._val("tariff_current_import_rate"),i=this._valStr("tariff_price_level");return i?`${e.toFixed(4)} ${t} · ${this._t(i.toLowerCase())}`:`${e.toFixed(4)} ${t}`}return""}_renderTypedStepper(e,t){const i=this._hass?.states[e],s=this._numVal(e),r=i?.attributes?.unit_of_measurement||"";return W`
            <div class="stepper-row">
                <span class="stepper-label">${this._t(t)}</span>
                <div class="stepper-controls">
                    <button class="stepper-minus" aria-label="Decrease"
                        @click=${()=>this._stepNumber(e,-1)}>−</button>
                    <input class="stepper-input" type="number"
                        .value=${String(s)}
                        @change=${t=>{const i=parseFloat(t.target.value);Number.isNaN(i)||this._setNumber(e,i)}}
                        @keydown=${e=>{"Enter"===e.key&&e.target.blur()}}>
                    ${r?W`<span class="stepper-unit">${r}</span>`:q}
                    <button class="stepper-plus" aria-label="Increase"
                        @click=${()=>this._stepNumber(e,1)}>+</button>
                </div>
            </div>
        `}_renderStepper(e,t){const i=this._hass?.states[e],s=this._numVal(e),r=i&&parseFloat(i.attributes.step)||1,a=i?.attributes?.unit_of_measurement||"",o=r<1?2:0,n=s.toFixed(o)+(a?" "+a:"");return W`
            <div class="stepper-row">
                <span class="stepper-label">${this._t(t)}</span>
                <div class="stepper-controls">
                    <button
                        class="stepper-minus"
                        aria-label="Decrease"
                        @click=${()=>this._stepNumber(e,-1)}
                        @pointerdown=${()=>this._startHold(e,-1)}
                        @pointerup=${()=>this._stopHold(e)}
                        @pointerleave=${()=>this._stopHold(e)}
                    >−</button>
                    <span class="stepper-value">${n}</span>
                    <button
                        class="stepper-plus"
                        aria-label="Increase"
                        @click=${()=>this._stepNumber(e,1)}
                        @pointerdown=${()=>this._startHold(e,1)}
                        @pointerup=${()=>this._stopHold(e)}
                        @pointerleave=${()=>this._stopHold(e)}
                    >+</button>
                </div>
            </div>
        `}_renderInfoTile(e,t,i,s){return W`
            <div class="info-tile">
                <ha-icon icon="${e}" style="--mdc-icon-size:18px;color:${t}"></ha-icon>
                <div class="info-tile-content">
                    <span class="info-tile-label">${this._t(i)}</span>
                    <span class="info-tile-value">${s}</span>
                </div>
            </div>
        `}_renderSectionBody(e,t){if("ev_econ"===e){const e=this._val("lifetime_ev_energy");if(!(e>0))return W`<div class="info-empty">${this._t("no_ev_data")}</div>`;const i=this._val("lifetime_ev_cost"),s=this._val("lifetime_ev_solar_share"),r=i/e;return W`
                <div class="info-tiles">
                    ${this._renderInfoTile("mdi:currency-usd","#8DC892","cost_per_kwh",r.toFixed(4)+" "+t+"/kWh")}
                    ${this._renderInfoTile("mdi:solar-power","#ff9800","solar_share",s.toFixed(1)+"%")}
                </div>
            `}if("investment"===e)return W`${this._renderTypedStepper("number.sem_system_investment_cost","system_investment_cost")}`;if("demand"===e){const e=this._val("monthly_consecutive_peak"),i=this._val("power_charge_cost");return W`
                <div class="info-tiles">
                    ${this._renderInfoTile("mdi:chart-bell-curve","#ff9800","monthly_peak",e.toFixed(2)+" kW")}
                    ${this._renderInfoTile("mdi:currency-usd","#f06292","demand_charge",i.toFixed(2)+" "+t)}
                </div>
                ${this._renderStepper("number.sem_demand_charge_rate","demand_charge_rate")}
            `}if("tariff"===e){const e=this._hass?.states["sensor.sem_tariff_current_import_rate"],i=this._hass?.states["sensor.sem_tariff_current_export_rate"],s=this._hass?.states[`${this._prefix}tariff_price_level`],r=e?.state??"—",a=e?.attributes?.unit_of_measurement||t,o=i?.state??"—",n=i?.attributes?.unit_of_measurement||t,l=s?.state??"—",c=this._entityExists("number.sem_electricity_import_rate"),d=this._entityExists("number.sem_electricity_export_rate");return W`
                <div class="info-tiles tariff-info-tiles">
                    ${this._renderInfoTile("mdi:transmission-tower-import","#488fc2","current_import_rate",`${r} ${a}`)}
                    ${this._renderInfoTile("mdi:transmission-tower-export","#8353d1","current_export_rate",`${o} ${n}`)}
                    ${this._renderInfoTile("mdi:signal-cellular-outline","#96CAEE","price_level",l?this._t(l):"—")}
                </div>
                ${c?this._renderStepper("number.sem_electricity_import_rate","current_import_rate"):q}
                ${d?this._renderStepper("number.sem_electricity_export_rate","current_export_rate"):q}
            `}return q}_renderSection(e,t){const i=this._collapsed[e.id],s=this._sectionSubtitle(e.id,t);return W`
            <div class="section">
                <div
                    class="section-header"
                    tabindex="0"
                    role="button"
                    aria-expanded="${!i}"
                    @click=${()=>this._toggleSection(e.id)}
                    @keydown=${t=>{"Enter"!==t.key&&" "!==t.key||(t.preventDefault(),this._toggleSection(e.id))}}
                >
                    <ha-icon icon="${e.icon}" style="--mdc-icon-size:20px;color:${e.color}"></ha-icon>
                    <span class="section-title-text">${this._t(e.titleKey)}</span>
                    <span class="section-subtitle">${s}</span>
                    <ha-icon
                        class="chevron"
                        icon="mdi:chevron-down"
                        style="--mdc-icon-size:18px;transform:rotate(${i?"-90deg":"0deg"});transition:transform 0.25s ease"
                    ></ha-icon>
                </div>
                ${i?q:W`
                    <div class="section-body">
                        ${this._renderSectionBody(e.id,t)}
                    </div>
                `}
            </div>
        `}render(){if(!this._config||!this._hass)return q;const e=me(this._hass);return W`
            <div class="wrap">
                ${ot.map(t=>this._renderSection(t,e))}
            </div>
        `}static get styles(){return a`
            :host { display: block; }
            .wrap {
                padding: 16px;
                position: relative;
                background:
                    radial-gradient(ellipse 70% 60% at 50% 25%, rgba(240,98,146,0.06) 0%, transparent 100%),
                    radial-gradient(circle at 2px 2px, rgba(128,128,128,0.05) 0.7px, transparent 0.7px);
                background-size: 100% 100%, 50px 50px;
                font-family: 'Segoe UI','Roboto',sans-serif;
                color: var(--primary-text-color, #e0e0e0);
            }

            /* ── Sections ── */
            .section {
                margin-bottom: 8px;
                border-radius: 14px;
                background: var(--secondary-background-color, rgba(255,255,255,0.06));
                border: 1px solid var(--divider-color, rgba(255,255,255,0.12));
                overflow: hidden;
                transition: border-color 0.2s;
            }
            .section:hover {
                border-color: rgba(255,255,255,0.18);
            }

            .section-header {
                display: flex; align-items: center; gap: 8px;
                padding: 12px 14px;
                cursor: pointer;
                user-select: none;
                -webkit-user-select: none;
                transition: background 0.15s;
            }
            .section-header:hover {
                background: rgba(255,255,255,0.10);
            }
            .section-title-text {
                font-size: 14px; font-weight: 600;
                white-space: nowrap;
            }
            .section-subtitle {
                flex: 1;
                font-size: 12px;
                color: var(--secondary-text-color, #999);
                text-align: right;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
                margin-right: 4px;
            }

            .section-body {
                padding: 0 14px 14px;
                overflow: hidden;
            }

            /* ── Number Stepper ── */
            .stepper-row {
                display: flex; align-items: center; justify-content: space-between;
                padding: 7px 0;
            }
            .stepper-label {
                font-size: 13px; font-weight: 500;
                flex: 1; min-width: 0;
                overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
            }
            .stepper-controls {
                display: flex; align-items: center; gap: 2px;
                flex-shrink: 0;
            }
            .stepper-minus, .stepper-plus {
                width: 30px; height: 30px;
                border-radius: 8px;
                border: 1px solid var(--divider-color, rgba(255,255,255,0.12));
                background: var(--secondary-background-color, rgba(255,255,255,0.06));
                color: var(--primary-text-color, #e0e0e0);
                font-size: 16px; font-weight: 600;
                cursor: pointer;
                display: flex; align-items: center; justify-content: center;
                transition: background 0.15s, border-color 0.15s;
                user-select: none;
                -webkit-user-select: none;
                touch-action: manipulation;
                padding: 0; line-height: 1;
            }
            .stepper-minus:hover, .stepper-plus:hover {
                background: rgba(255,255,255,0.10);
                border-color: var(--primary-color, #42a5f5);
            }
            .stepper-input {
                width: 110px; text-align: center;
                background: transparent; border: 1px solid rgba(150,202,238,0.35);
                border-radius: 6px; color: inherit; font: inherit;
                padding: 3px 6px; -moz-appearance: textfield;
            }
            .stepper-input::-webkit-outer-spin-button,
            .stepper-input::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
            .stepper-unit { font-size: 12px; opacity: 0.75; }
            .stepper-value {
                font-size: 13px; font-weight: 600;
                min-width: 60px; text-align: center;
                font-variant-numeric: tabular-nums;
            }

            /* ── Info tiles ── */
            .info-tiles {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 8px;
                margin: 8px 0;
            }
            .tariff-info-tiles {
                grid-template-columns: 1fr 1fr 1fr;
            }
            @media (max-width: 480px) {
                .info-tiles { grid-template-columns: 1fr; }
                .tariff-info-tiles { grid-template-columns: 1fr 1fr; }
            }
            .info-tile {
                display: flex; align-items: flex-start; gap: 8px;
                padding: 10px;
                border-radius: 10px;
                background: rgba(255,255,255,0.03);
                border: 1px solid var(--divider-color, rgba(255,255,255,0.12));
            }
            .info-tile ha-icon { margin-top: 1px; flex-shrink: 0; }
            .info-tile-content { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
            .info-tile-label {
                font-size: 11px; font-weight: 500; text-transform: uppercase;
                color: var(--secondary-text-color, #999);
                letter-spacing: 0.3px;
                white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
            }
            .info-tile-value {
                font-size: 13px; font-weight: 600;
                font-variant-numeric: tabular-nums;
            }

            /* ── EV no data ── */
            .info-empty {
                font-size: 13px;
                color: var(--secondary-text-color, #999);
                text-align: center;
                padding: 12px 0;
                font-style: italic;
            }
        `}getCardSize(){return 8}static getStubConfig(){return{entity_prefix:"sensor.sem_"}}},{type:"custom:sem-costs-detail-card",name:"SEM Costs Detail Card",description:"Financial details — EV economics, investment, demand charge, and tariff rates",preview:!1});const nt="sensor.sem_";$e("sem-charger-status-card",class extends ke{constructor(){super(),this._chargers=[],this._lastStateCount=0}set hass(e){this._hass,this._hass=e;const t=e?.language,i="function"==typeof semLocalize;let s=!1;if((t!==this._lang||i&&!this._localizeReady)&&(this._lang=t,this._localizeReady=i,s=!0),this._isFrozen()&&!s)return;if(this._chargers?.length>0&&!s){const t=this._config?.entity_prefix||nt,i=e.states[`${t}charger_${this._chargers[0]}_power`]?.state;if("unavailable"===i||"unknown"===i)return}const r=Object.keys(e.states).length;if(r!==this._lastStateCount){this._lastStateCount=r;const t=[];for(const i of Object.keys(e.states)){if(i.includes("_flow_"))continue;const e=i.match(/^sensor\.sem_charger_(.+)_power$/);e&&t.push(e[1])}this._chargers=t}const a=this._config?.entity_prefix||nt,o=this._chargers.map(t=>[`charger_${t}_power`,`charger_${t}_session_energy`,`charger_${t}_session_solar_share`,`charger_${t}_taper_trend`].map(t=>e.states[`${a}${t}`]?.state||"").join(":")).join("|");(o!==this._lastKey||s)&&(this._lastKey=o,this._scheduleUpdate())}get hass(){return this._hass}setConfig(e){super.setConfig(e),this._prefix=e.entity_prefix||nt}_val(e,t=0){const i=this._hass?.states[`${this._prefix}${e}`];return i&&"unavailable"!==i.state&&"unknown"!==i.state?parseFloat(i.state)??t:t}_valStr(e){const t=this._hass?.states[`${this._prefix}${e}`];return t&&"unavailable"!==t.state&&"unknown"!==t.state?t.state:""}_chargerName(e){const t=this._hass?.states[`${this._prefix}charger_${e}_power`];let i=e.replace(/_/g," ").replace(/\b\w/g,e=>e.toUpperCase());return t?.attributes?.friendly_name&&(i=t.attributes.friendly_name.replace(/^SEM\s+/i,"").replace(/\s+Power$/i,"")),i}_renderChargerTile(e){const t=this._val(`charger_${e}_power`),i=this._val(`charger_${e}_session_energy`),s=this._val(`charger_${e}_session_solar_share`),r=this._valStr(`charger_${e}_taper_trend`)||"stable",a=this._t(r),o=this._chargerName(e),n=t>50,l=n?"#8DC892":"#888",c=n?this._t("charging"):this._t("idle");return W`
            <div class="charger-tile">
                <div class="charger-glow" style="opacity:${n?"0.15":"0"}"></div>
                <div class="charger-header">
                    <ha-icon icon="mdi:ev-station" style="--mdc-icon-size:20px;color:${l}"></ha-icon>
                    <span class="charger-name">${o}</span>
                    <span class="charger-status" style="color:${l}">${c}</span>
                </div>
                <div class="charger-metrics">
                    <div class="metric">
                        <span class="metric-value">${t.toFixed(0)}</span>
                        <span class="metric-unit">W</span>
                        <span class="metric-label">${this._t("power")}</span>
                    </div>
                    <div class="metric">
                        <span class="metric-value">${i.toFixed(1)}</span>
                        <span class="metric-unit">kWh</span>
                        <span class="metric-label">${this._t("session")}</span>
                    </div>
                    <div class="metric">
                        <span class="metric-value">${s.toFixed(0)}</span>
                        <span class="metric-unit">%</span>
                        <span class="metric-label">${this._t("solar")}</span>
                    </div>
                    <div class="metric">
                        <span class="metric-value taper-${r}">${a}</span>
                        <span class="metric-label">${this._t("taper")}</span>
                    </div>
                </div>
            </div>
        `}render(){return this._config&&this._hass?W`
            <div class="card-wrap">
                <div class="card-title">${this._t("charger_status")}</div>
                <div class="card-subtitle">${this._chargers.length} ${this._t("chargers_configured")}</div>
                <div class="charger-grid">
                    ${this._chargers.map(e=>this._renderChargerTile(e))}
                </div>
            </div>
        `:q}static get styles(){return a`
            :host { display: block; }
            .card-wrap {
                padding: 16px;
                position: relative;
            }
            .card-title {
                font-size: 1.1em;
                font-weight: 500;
                color: var(--primary-text-color, #e0e0e0);
                margin-bottom: 4px;
            }
            .card-subtitle {
                font-size: 0.85em;
                color: var(--secondary-text-color, #999);
                margin-bottom: 16px;
            }
            .charger-grid {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
                gap: 12px;
            }
            .charger-tile {
                position: relative;
                background: var(--secondary-background-color, rgba(255,255,255,0.06));
                border: 1px solid var(--divider-color, rgba(255,255,255,0.12));
                border-radius: 12px;
                padding: 14px;
                overflow: hidden;
            }
            .charger-glow {
                position: absolute;
                top: -20px; right: -20px;
                width: 80px; height: 80px;
                border-radius: 50%;
                background: radial-gradient(circle, rgba(141,200,146,0.4), transparent 70%);
                pointer-events: none;
                transition: opacity 0.5s ease;
            }
            .charger-header {
                display: flex;
                align-items: center;
                gap: 8px;
                margin-bottom: 12px;
            }
            .charger-name {
                flex: 1;
                font-weight: 500;
                color: var(--primary-text-color, #e0e0e0);
                font-size: 0.95em;
            }
            .charger-status {
                font-size: 0.8em;
                font-weight: 500;
                text-transform: uppercase;
                letter-spacing: 0.05em;
            }
            .charger-metrics {
                display: grid;
                grid-template-columns: repeat(4, 1fr);
                gap: 8px;
                text-align: center;
            }
            .metric-value {
                display: block;
                font-size: 1.15em;
                font-weight: 600;
                color: var(--primary-text-color, #e0e0e0);
            }
            .metric-unit {
                font-size: 0.8em;
                color: var(--secondary-text-color, #999);
                margin-left: 1px;
            }
            .metric-label {
                display: block;
                font-size: 0.8em;
                color: var(--secondary-text-color, #999);
                margin-top: 2px;
                text-transform: uppercase;
                letter-spacing: 0.03em;
            }
            .taper-rising  { color: #f06292; }
            .taper-falling { color: #8DC892; }
            .taper-stable  { color: var(--secondary-text-color, #999); }
        `}getCardSize(){return Math.max(2,this._chargers.length)}static getStubConfig(){return{}}},{type:"sem-charger-status-card",name:"SEM Charger Status",description:"Multi-charger status display with per-charger tiles"});const lt="sensor.sem_",ct=["#8DC892","#64B5F6"];$e("sem-ev-status-card",class extends ke{static get properties(){return{...super.properties,_showHelp:{state:!0}}}constructor(){super(),this._chargers=[],this._lastStateCount=0,this._showHelp=!1,this._boundVisibility=()=>{document.hidden||this.requestUpdate()}}connectedCallback(){super.connectedCallback(),document.addEventListener("visibilitychange",this._boundVisibility)}disconnectedCallback(){super.disconnectedCallback(),document.removeEventListener("visibilitychange",this._boundVisibility)}_toggleHelp(){this._showHelp=!this._showHelp}set hass(e){this._hass,this._hass=e;const t=e?.language,i="function"==typeof semLocalize;let s=!1;if((t!==this._lang||i&&!this._localizeReady)&&(this._lang=t,this._localizeReady=i,s=!0),this._isFrozen()&&!s)return;const r=Object.keys(e.states).length;if(r!==this._lastStateCount){this._lastStateCount=r;const t=[];for(const i of Object.keys(e.states)){if(i.includes("_flow_"))continue;const e=i.match(/^sensor\.sem_charger_(.+)_power$/);e&&t.push(e[1])}this._chargers=t}const a=this._config?.entity_prefix||lt;let o=["ev_connected","ev_charging","ev_power","calculated_current","session_energy","session_solar_share","session_cost","daily_ev_energy","energy_ev_solar_percentage","charging_state"].map(t=>{const i="ev_connected"===t||"ev_charging"===t?"binary_sensor.sem_":a;return e.states[`${i}${t}`]?.state||""}).join(",");if(this._chargers.length>=1){o+="|"+this._chargers.map(t=>[`charger_${t}_power`,`charger_${t}_session_energy`,`charger_${t}_session_energy_external`,`charger_${t}_daily_energy`,`charger_${t}_session_solar_share`,`charger_${t}_estimated_soc`,`charger_${t}_vehicle_soc`,`charger_${t}_commanded_current`].map(t=>e.states[`${a}${t}`]?.state||"").join(":")).join("|"),o+="|"+this._chargers.map(t=>e.states[`switch.sem_charger_${t}_night_charging`]?.state||"").join(":"),o+="|"+this._chargers.map(t=>[e.states[`time.sem_charger_${t}_target_time`]?.state||"",e.states[`switch.sem_charger_${t}_tariff_optimized`]?.state||""].join(":")).join("|");const t=e.states[`${a}charging_state`]?.attributes||{};o+="|"+[t.ev_tariff_waiting,t.ev_deadline_reachable,t.ev_next_cheap_window].join(":"),o+="|"+this._chargers.map(t=>e.states[`number.sem_charger_${t}_daily_ev_target`]?.state||"").join(":"),o+="|"+this._chargers.map(t=>[e.states[`select.sem_charger_${t}_ev_target_type`]?.state||"",e.states[`number.sem_charger_${t}_target_soc`]?.state||"",e.states[`number.sem_charger_${t}_daily_ev_target_max`]?.state||"",e.states[`number.sem_charger_${t}_target_soc_max`]?.state||"",e.states[`number.sem_charger_${t}_ev_battery_capacity_kwh`]?.state||"",e.states[`number.sem_charger_${t}_ev_kwh_per_100km`]?.state||""].join(":")).join("|"),o+="|"+(e.states[`${a}ev_remaining_range`]?.state||"")}o+="|"+this._localizeReady+"|"+this._lang,(o!==this._lastKey||s)&&(this._lastKey=o,this._scheduleUpdate())}get hass(){return this._hass}setConfig(e){super.setConfig(e),this._prefix=e.entity_prefix||lt}_binaryState(e){const t=this._hass?.states[`binary_sensor.sem_${e}`];return"on"===t?.state}_val(e,t=0){const i=this._hass?.states[`${this._prefix}${e}`];return i&&"unavailable"!==i.state&&"unknown"!==i.state?parseFloat(i.state)??t:t}_valStr(e){const t=this._hass?.states[`${this._prefix}${e}`];return t?.state||""}_entityVal(e,t=0){const i=this._frozenEntities[e];if(i)return i.value;const s=this._hass?.states[e];return s&&"unavailable"!==s.state&&"unknown"!==s.state?parseFloat(s.state)??t:t}_fmt(e,t=1){return null==e||isNaN(e)?"—":e.toFixed(t)}_chargerName(e){const t=this._hass?.states[`${this._prefix}charger_${e}_power`];let i=e.replace(/_/g," ").replace(/\b\w/g,e=>e.toUpperCase());return t?.attributes?.friendly_name&&(i=t.attributes.friendly_name.replace(/^SEM\s+/i,"").replace(/\s+Power$/i,"")),i}_renderSocGauge(e,t=!1){const i=null!=e?Math.max(0,Math.min(100,e)):0,s=i>60?"#8DC892":i>30?"#ff9800":"#f06292",r=Math.max(2,i/100*52);return W`
            <svg viewBox="0 0 44 76" width="44" height="76">
                <rect x="14" y="0" width="16" height="5" rx="2" fill="rgba(255,255,255,0.15)"/>
                <rect x="6" y="4" width="32" height="60" rx="4"
                    fill="none" stroke="rgba(255,255,255,0.15)" stroke-width="2"/>
                <rect x="9" y="${52-r+7}" width="26" height="${r}" rx="2"
                    fill="${s}" opacity="0.7"/>
                <text x="22" y="40" text-anchor="middle"
                    fill="white" font-size="14" font-weight="700"
                    font-family="'Segoe UI','Roboto',sans-serif"
                    opacity="0.95">
                    ${null!=e?(t?"~":"")+Math.round(e)+"%":"—"}
                </text>
            </svg>
        `}_renderPlanStrip(e){const t=this._hass?.states["sensor.sem_charging_state"],i=e?t?.attributes?.per_charger_plans?.[e]:null,s=Array.isArray(i)&&i.length>0,r=s?i:t?.attributes?.today_plan||[];if(!Array.isArray(r)||r.length<2)return q;const a=new Set(["ev_charge_start","ev_min_reached","ev_deadline"]);if(!r.some(e=>a.has(e.kind)))return q;const o=Date.now(),n=432e5,l=o+n,c=e=>Math.max(0,Math.min(100,(e-o)/n*100)),d=r.filter(e=>["now","night_open","ev_charge_start","ev_min_reached","ev_deadline"].includes(e.kind));d.sort((e,t)=>new Date(e.when)-new Date(t.when));const p=s?r.some(e=>"ev_charge_start"===e.kind&&"plan_ev_charge_tariff"===e.detail):!!t?.attributes?.ev_tariff_waiting,h=[];let _=o,g="idle";for(const e of d){const t=new Date(e.when).getTime(),i=Math.min(t,l);i>_&&h.push({s:_,e:i,state:g}),_=Math.max(_,i),"night_open"===e.kind?g=p?"wait":"charging":"ev_charge_start"===e.kind?g="charging":("ev_min_reached"===e.kind||"ev_deadline"===e.kind)&&(g="done")}_<l&&h.push({s:_,e:l,state:g});const u=[];for(const e of r){const t=new Date(e.when).getTime();if("expensive_start"===e.kind&&t<l){const i=e.values?.end;if(i){const[e,s]=i.split(":").map(Number),r=new Date(t);r.setHours(e,s,0,0),r.getTime()<t&&r.setDate(r.getDate()+1),u.push({s:t,e:Math.min(r.getTime(),l),kind:"expensive"})}}else if("cheap_start"===e.kind&&t<l){const i=e.values?.end;if(i){const[e,s]=i.split(":").map(Number),r=new Date(t);r.setHours(e,s,0,0),r.getTime()<t&&r.setDate(r.getDate()+1),u.push({s:t,e:Math.min(r.getTime(),l),kind:"cheap"})}}}const f=e=>({idle:"#566072",wait:"#8353d1",charging:"#8DC892",done:"#4db6ac"}[e]||"#566072"),m=e=>"cheap"===e?"#43a047":"#f06292",y=this._hass?.config?.time_zone||void 0,v=[];for(let e=0;e<=12;e+=3){const t=o+3600*e*1e3,i=new Date(t).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit",timeZone:y});v.push({x:c(t),label:i})}return W`
            <div class="plan-strip" title="${this._t("today_plan_title")} (12h)">
                <div class="strip-title">
                    <ha-icon icon="mdi:chart-timeline" style="--mdc-icon-size:13px;color:#5BC8D8"></ha-icon>
                    <span>${this._t("plan_strip_title")}</span>
                </div>
                <svg viewBox="0 0 ${100} 16" preserveAspectRatio="none" class="strip-svg">
                    ${h.map(e=>j`
                        <rect x="${c(e.s)}" y="5" width="${c(e.e)-c(e.s)}"
                              height="10" fill="${f(e.state)}" />
                    `)}
                    ${u.map(e=>j`
                        <rect x="${c(e.s)}" y="0" width="${c(e.e)-c(e.s)}"
                              height="3" fill="${m(e.kind)}"
                              opacity="0.75" />
                    `)}
                </svg>
                <div class="strip-axis">
                    ${v.map(e=>W`
                        <span class="tick" style="left: ${e.x}%">${e.label}</span>
                    `)}
                </div>
                <div class="strip-legend">
                    <span><i style="background:${f("idle")}"></i>${this._t("plan_strip_idle")}</span>
                    <span><i style="background:${f("wait")}"></i>${this._t("plan_strip_wait")}</span>
                    <span><i style="background:${f("charging")}"></i>${this._t("plan_strip_charging")}</span>
                    <span><i style="background:${f("done")}"></i>${this._t("plan_strip_done")}</span>
                    <span><i class="line" style="background:${m("cheap")}"></i>${this._t("plan_strip_cheap")}</span>
                    <span><i class="line" style="background:${m("expensive")}"></i>${this._t("plan_strip_expensive")}</span>
                </div>
                ${this._showHelp?W`
                    <div class="setting-help strip-help">${this._t("plan_strip_help")}</div>
                `:q}
            </div>
        `}_renderRangeSlider(e,t,i){const s=this._hass?.states[e],r=this._hass?.states[t],a=i?"%":" kWh",o=e=>i?String(Math.round(e)):this._fmt(e,e%1==0?0:1);if(!s||!r){const t=this._entityVal(e,i?80:10);return W`<div class="ct-row">
                <span class="ct-label">${this._t("charge_to")}</span>
                <span class="ct-ctl"><span class="ct-val clickable"
                    @click=${()=>this.dispatchEvent(new CustomEvent("hass-more-info",{bubbles:!0,composed:!0,detail:{entityId:e}}))}
                >${o(t)}${a}</span></span></div>`}const n=Math.min(parseFloat(s.attributes.min??0),parseFloat(r.attributes.min??0)),l=Math.max(parseFloat(s.attributes.max??100),parseFloat(r.attributes.max??100)),c=l-n||1;let d=this._entityVal(e,i?80:10),p=this._entityVal(t,100);p<d&&(p=d);const h=(d-n)/c*100,_=(p-n)/c*100,g=p>=l-1e-6,u=parseFloat(this._hass?.states[e]?.attributes?.step)||(l>50?1:5),f=Math.max(u,.02*(l-n)),m=p-d<f-1e-6;return W`
            <div class="range-wrap">
                <div class="range-labels">
                    <span>${this._t("at_least")} <b style="color:#8DC892">${o(d)}${a}</b></span>
                    <span>${this._t("up_to")} <b style="color:#ff9800">${g?this._t("full"):o(p)+a}</b></span>
                </div>
                <div class="range-track">
                    <div class="range-fill" style="left:${h}%;width:${Math.max(0,_-h)}%"></div>
                    <div class="range-handle range-handle-min" style="left:${h}%"
                        @pointerdown=${i=>this._rangeHandleStart(i,"min",e,t,n,l)}></div>
                    <div class="range-handle range-handle-max" style="left:${_}%"
                        @pointerdown=${i=>this._rangeHandleStart(i,"max",e,t,n,l)}></div>
                    ${m?W`
                        <span class="range-split"
                              style="left:${h}%"
                              title="${this._t("separate_handles")}"
                              @click=${i=>{i.stopPropagation();const s=p-f;s>=n?this._setNumber(e,s):this._setNumber(t,Math.min(l,d+f))}}>
                            <ha-icon icon="mdi:arrow-split-vertical"
                                     style="--mdc-icon-size:14px"></ha-icon>
                        </span>
                    `:q}
                </div>
            </div>`}_rangeHandleStart(e,t,i,s,r,a){e.stopPropagation(),e.preventDefault();const o=e.currentTarget.closest(".range-track");if(!o)return;const n="min"===t?i:s,l="min"===t?s:i,c=this._hass?.states[n],d=parseFloat(c?.attributes?.step)||(a>50?1:.5),p=a-r||1,h=e=>{const i=o.getBoundingClientRect();let s=(e-i.left)/(i.width||1);s=Math.max(0,Math.min(1,s));let n=Math.round((r+s*p)/d)*d;const c=this._entityVal(l,"min"===t?a:r);return n="min"===t?Math.min(n,c):Math.max(n,c),Math.max(r,Math.min(a,n))},_=e=>{this._freezeEntity(n,h(e.clientX)),this.requestUpdate()},g=e=>{window.removeEventListener("pointermove",_),window.removeEventListener("pointerup",g),window.removeEventListener("pointercancel",g),this._setNumber(n,h(e.clientX))};window.addEventListener("pointermove",_),window.addEventListener("pointerup",g),window.addEventListener("pointercancel",g)}_renderChargerSection(e,t){const i=ct[t%ct.length],s=this._val(`charger_${e}_power`,0),r=this._val(`charger_${e}_session_energy_external`,0),a=this._val(`charger_${e}_session_energy`,0),o=r>0?r:a,n=this._val(`charger_${e}_daily_energy`,0),l=this._val("energy_ev_solar_percentage",0),c=this._val(`charger_${e}_vehicle_soc`,null)??this._val("vehicle_soc",null),d=this._val(`charger_${e}_estimated_soc`,null),p=null!=c?c:d,h=null==c&&null!=d,_=this._chargerName(e),g=this._hass?.states[`binary_sensor.sem_charger_${e}_connected`],u="on"===g?.state,f=s>50,m=f?this._t("charging"):u?this._t("connected"):this._t("idle"),y=this._val(`charger_${e}_commanded_current`,0),v=this._entityVal(`number.sem_charger_${e}_minimum_current`,6),x=this._entityVal(`number.sem_charger_${e}_ev_battery_capacity_kwh`,40),b=this._entityVal(`number.sem_charger_${e}_ev_kwh_per_100km`,18),$=`select.sem_charger_${e}_charge_mode`,w=this._stateAttrs($),k=this._stateStr($)||"min_plus_solar",S=w.options||["solar_only","min_plus_solar","always_max","off"],C={solar_only:this._t("charge_mode_solar_only"),solar_plus_cheap:this._t("charge_mode_solar_plus_cheap"),min_plus_solar:this._t("charge_mode_min_plus_solar"),always_max:this._t("charge_mode_always_max"),off:this._t("charge_mode_off")},z=Math.round(this._entityVal("number.sem_battery_buffer_soc",70)),M=Math.round(this._entityVal("number.sem_battery_priority_soc",30)),E=e=>(this._t(e)||"").replace(/\{buffer\}/g,z).replace(/\{priority\}/g,M),D=E(`charge_mode_hint_${k}_surplus`),F=E(`charge_mode_hint_${k}_overnight`),I=E(`charge_mode_hint_${k}_battery`),B=`select.sem_charger_${e}_ev_target_type`,N=this._stateStr(B)||"kwh",A=this._stateAttrs(B).options||["kwh"],T="soc"===N,P=T?`number.sem_charger_${e}_target_soc`:`number.sem_charger_${e}_daily_ev_target`,R=T?`number.sem_charger_${e}_target_soc_max`:`number.sem_charger_${e}_daily_ev_target_max`,L=`time.sem_charger_${e}_target_time`,O=this._stateStr(L),U=O?O.slice(0,5):"—",H=this._stateAttrs(`${this._prefix}charging_state`),j=!1===H.ev_deadline_reachable,G=H.ev_next_cheap_window;let K="";if(G)try{const e=new Date(G);isNaN(e)||(K=e.toLocaleTimeString([],{hour:"2-digit",minute:"2-digit",timeZone:this._hass?.config?.time_zone||void 0}))}catch(e){}const V="solar_plus_cheap"===k&&K,Y=this._entityVal(P,T?80:10),X=T?Math.max(0,(Y-p)/100*x):Math.max(0,Y-n),Z=b>0?Math.round(X/b*100):null,J=A.length>1?W`<select class="ct-unit" .value=${N}
                    @click=${e=>e.stopPropagation()}
                    @change=${e=>this._selectOption(B,e.target.value)}>
                    ${A.map(e=>W`<option value=${e} ?selected=${e===N}>${"soc"===e?"%":"kWh"}</option>`)}
                </select>`:W`<span class="ct-unit-static">${T?"%":"kWh"}</span>`;return W`
            <div class="charger-section">
                <div class="charger-header">
                    <div class="charger-dot" style="background:${i}"></div>
                    <span class="charger-name">${_}</span>
                    <span class="charger-status" style="color:${f?i:""}">${m}${y>0?W` <span class="charger-set">(${Math.round(y)}&nbsp;A)</span>`:q}</span>
                </div>

                <div class="charger-body">
                    <div class="charger-soc" title="${h?this._t("soc_estimated_hint"):""}">
                        ${this._renderSocGauge(p,h)}
                        <span class="soc-label">${h?this._t("soc_estimated_label"):"SOC"}</span>
                    </div>

                    <div class="charger-metrics">
                        <div class="cm-row">
                            <span class="cm-label">${this._t("power")}</span>
                            <span class="cm-value" style="color:${f?i:""}">${ge(s)}</span>
                        </div>
                        <div class="cm-row">
                            <span class="cm-label">${this._t("today")}</span>
                            <span class="cm-value">${this._fmt(n,1)} kWh</span>
                        </div>
                        <div class="cm-row">
                            <span class="cm-label">${this._t("session")}</span>
                            <span class="cm-value">${this._fmt(o,1)} kWh</span>
                        </div>
                        <div class="cm-row">
                            <span class="cm-label">${this._t("solar_share")}</span>
                            <span class="cm-value" style="color:#ff9800">${this._fmt(l,0)}%</span>
                        </div>
                        <!-- (#440) "Charge Tonight" and "Nights Until Charge"
                             rows removed. The underlying skip-decision wiring
                             was removed alongside; charge mode is the sole
                             authority on whether to charge at night. -->
                    </div>
                </div>

                <div class="charge-target-group">
                    <div class="ct-title">
                        <ha-icon icon="mdi:target" style="--mdc-icon-size:14px;color:#8DC892"></ha-icon>
                        ${this._t("charge_target")}
                        ${null!=Z&&Z>0?W`<span class="ct-range">· +${Z} km</span>`:q}
                        <span class="ct-spacer"></span>
                        ${J}
                    </div>
                    ${this._renderRangeSlider(P,R,T)}
                    <!-- #277 Phase B.2: one named Charge mode selector
                         replaces the legacy ev_grid_charging + nested
                         ev_tariff_mode toggles. Options come from the HA
                         entity itself (solar_plus_cheap is hidden when no
                         dynamic tariff is configured, per Q1). The hint
                         line under it explains what the selected mode
                         actually does — cuts the toggle-soup mystery the
                         #247 review flagged. -->
                    <div class="ct-row">
                        <span class="ct-label">${this._t("charge_mode")}</span>
                        <span class="ct-ctl">
                            <select class="ct-mode-select"
                                    .value=${k}
                                    @click=${e=>e.stopPropagation()}
                                    @change=${e=>this._selectOption($,e.target.value)}>
                                ${S.map(e=>W`
                                    <option value=${e} ?selected=${e===k}>
                                        ${C[e]||e}
                                    </option>`)}
                            </select>
                        </span>
                    </div>
                    ${this._showHelp?W`
                    <div class="ct-subhint">
                        <div class="ct-hint-row">
                            <span class="ct-hint-label">${this._t("hint_label_surplus")}:</span>
                            <span class="ct-hint-text">${D}</span>
                        </div>
                        <div class="ct-hint-row">
                            <span class="ct-hint-label">${this._t("hint_label_overnight")}:</span>
                            <span class="ct-hint-text">${F}</span>
                        </div>
                        <div class="ct-hint-row">
                            <span class="ct-hint-label">${this._t("hint_label_battery")}:</span>
                            <span class="ct-hint-text">${I}</span>
                        </div>
                        ${V?W`
                            <div class="ct-hint-row ct-hint-extra">
                                <span class="ct-hint-label">${this._t("ev_next_cheap")}:</span>
                                <span class="ct-hint-text"><b style="color:#8DC892">${K}</b></span>
                            </div>
                        `:q}
                    </div>
                    `:V?W`
                        <div class="ct-cheap-hint">
                            <span class="ct-hint-label">${this._t("ev_next_cheap")}:</span>
                            <b style="color:#8DC892">${K}</b>
                        </div>
                    `:q}
                    <div class="ct-row clickable"
                        @click=${()=>this.dispatchEvent(new CustomEvent("hass-more-info",{bubbles:!0,composed:!0,detail:{entityId:L}}))}>
                        <span class="ct-label">${this._t("ev_charge_by")}</span>
                        <span class="ct-ctl ct-time">
                            <ha-icon icon="mdi:clock-end" style="--mdc-icon-size:13px;color:#5BC8D8"></ha-icon>
                            ${U}
                        </span>
                    </div>
                    ${j?W`
                        <div class="ct-warn">
                            <ha-icon icon="mdi:clock-alert" style="--mdc-icon-size:14px;color:#f06292"></ha-icon>
                            <span>${this._t("ev_deadline_unreachable_short")}</span>
                        </div>
                    `:q}
                    ${this._renderPlanStrip(e)}
                </div>

                <div class="charger-settings ${this._showHelp?"help-mode":""}">
                    ${""}
                    <div class="setting-cell">
                        <div
                            class="setting-item clickable"
                            @click=${()=>{const t=new CustomEvent("hass-more-info",{bubbles:!0,composed:!0,detail:{entityId:`number.sem_charger_${e}_minimum_current`}});this.dispatchEvent(t)}}
                        >
                            <ha-icon icon="mdi:speedometer-slow" style="--mdc-icon-size:16px;color:#ff9800"></ha-icon>
                            <span class="setting-value">${this._fmt(v,0)}A</span>
                        </div>
                        ${this._showHelp?W`<div class="setting-help">${this._t("tile_help_min_amps")}</div>`:q}
                    </div>
                    <div class="setting-cell">
                        <div
                            class="setting-item clickable"
                            @click=${()=>{const t=new CustomEvent("hass-more-info",{bubbles:!0,composed:!0,detail:{entityId:`number.sem_charger_${e}_ev_battery_capacity_kwh`}});this.dispatchEvent(t)}}
                        >
                            <ha-icon icon="mdi:car-battery" style="--mdc-icon-size:16px;color:#8DC892"></ha-icon>
                            <span class="setting-value">${this._fmt(x,0)} kWh</span>
                        </div>
                        ${this._showHelp?W`<div class="setting-help">${this._t("tile_help_capacity")}</div>`:q}
                    </div>
                    <div class="setting-cell">
                        <div
                            class="setting-item clickable"
                            @click=${()=>{const t=new CustomEvent("hass-more-info",{bubbles:!0,composed:!0,detail:{entityId:`number.sem_charger_${e}_ev_kwh_per_100km`}});this.dispatchEvent(t)}}
                        >
                            <ha-icon icon="mdi:map-marker-distance" style="--mdc-icon-size:16px;color:#5BC8D8"></ha-icon>
                            <span class="setting-value">${this._fmt(b,0)} kWh/100km</span>
                        </div>
                        ${this._showHelp?W`<div class="setting-help">${this._t("tile_help_consumption")}</div>`:q}
                    </div>
                    <ha-icon
                        class="ev-help-toggle ${this._showHelp?"on":""}"
                        icon="${this._showHelp?"mdi:help-circle":"mdi:help-circle-outline"}"
                        title="${this._t("zone_help_toggle")}"
                        @click=${()=>this._toggleHelp()}
                        style="--mdc-icon-size:16px"
                    ></ha-icon>
                </div>
            </div>
        `}render(){if(!this._config||!this._hass)return q;const e=this._binaryState("ev_connected"),t=this._chargers&&this._chargers.length?this._chargers.reduce((e,t)=>e+this._val(`charger_${t}_power`,0),0):this._val("ev_power",0),i=t>50;this._val("calculated_current",0),this._val("session_energy",0);const s=this._val("energy_ev_solar_percentage",0),r=this._val("session_cost",0),a=this._val("daily_ev_energy",0);this._valStr("charging_state");const o=me(this._hass),n=i?"wrap state-charging":e?"wrap state-connected":"wrap state-disconnected",l=i?this._t("charging"):e?this._t("connected"):this._t("disconnected"),c=i?"status-value charging":e?"status-value connected":"status-value disconnected";return W`
            <svg class="glow-svg">
                <defs>
                    <filter id="ev-glow" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="3" result="blur"/>
                        <feFlood flood-color="#8DC892" flood-opacity="0.3" result="color"/>
                        <feComposite in="color" in2="blur" operator="in" result="glow"/>
                        <feMerge><feMergeNode in="glow"/><feMergeNode in="SourceGraphic"/></feMerge>
                    </filter>
                    <filter id="ev-glow-soft" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="6" result="blur"/>
                        <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
                    </filter>
                </defs>
            </svg>

            <ha-card>
                <div class="${n}">
                    <div class="hero">
                        <div class="ev-icon-area">
                            <svg viewBox="0 0 100 100">
                                <circle class="glow-ring" cx="50" cy="50" r="42" style="opacity:${i?"0.6":e?"0.25":"0.08"}"/>
                                <circle class="ring-bg" cx="50" cy="50" r="42"/>
                                <circle class="ring-fill" cx="50" cy="50" r="39"/>
                                <g class="charger-icon" transform="translate(50,46)">
                                    <rect x="-10" y="-16" width="20" height="26" rx="3"/>
                                    <rect x="-6.5" y="-11" width="13" height="10" rx="2"/>
                                    <path d="M-1.5,-1 L0,4 L1.5,-1"/>
                                    <line x1="0" y1="10" x2="0" y2="15"/>
                                    <circle class="indicator-dot" cx="0" cy="18" r="2" stroke="none"/>
                                </g>
                                <g class="lightning-bolt" transform="translate(50,42)" style="opacity:${i?"1":"0"}">
                                    <path d="M-2,-8 L-4,1 L-0.5,0 L-1,8 L4,-1 L0.5,0 L2,-8Z" stroke="none"/>
                                </g>
                            </svg>
                        </div>

                        ${this._chargers.length>=1?W`
                            <!-- #356: when at least one per-charger section
                                 will render below, the hero only shows a
                                 single status/power line. The per-charger
                                 section repeats today/session/solar-share/
                                 power for each charger, so duplicating them
                                 here as well produced the "4 tiles per
                                 charger" appearance the user reported. -->
                            <div class="metrics-col compact">
                                <div class="metric-row">
                                    <span class="metric-label">${this._t("status")}</span>
                                    <span class="${c}">${l}</span>
                                </div>
                                ${i?W`
                                    <div class="metric-row power-row">
                                        <span class="metric-label">${this._t("power")}</span>
                                        <span class="metric-value power-value">${ge(t)}</span>
                                    </div>
                                `:q}
                            </div>
                        `:W`
                            <div class="metrics-col">
                                <div class="metric-row">
                                    <span class="metric-label">${this._t("status")}</span>
                                    <span class="${c}">${l}</span>
                                </div>
                                ${i?W`
                                    <div class="metric-row power-row">
                                        <span class="metric-label">${this._t("power")}</span>
                                        <span class="metric-value power-value">${ge(t)}</span>
                                    </div>
                                `:q}
                                <div class="metric-row">
                                    <span class="metric-label">${this._t("today")}</span>
                                    <span class="metric-value">${this._fmt(a,1)} kWh</span>
                                </div>
                                <div class="metric-row">
                                    <span class="metric-label">${this._t("solar_share")}</span>
                                    <span class="metric-value solar-share-value">${this._fmt(s,0)}%</span>
                                </div>
                            </div>
                        `}
                    </div>

                    <!-- Session cost chip stays on for 0- and 1-charger
                         installs (M3 reviewer note): the global
                         sem_session_cost sensor IS the single charger's
                         cost. Only hide for multi-charger setups where
                         the global is a fleet aggregate and per-charger
                         attribution lives in each section's metrics. -->
                    ${this._chargers.length>1?q:W`
                        <div class="bottom-bar">
                            <div class="chip">
                                <span class="chip-label">${this._t("session_cost")}</span>
                                <span class="cost-chip-value">${this._fmt(r,2)} ${o}</span>
                            </div>
                        </div>
                    `}

                    ${this._chargers.length>=1?W`
                        <div class="charger-sections">
                            ${this._chargers.map((e,t)=>this._renderChargerSection(e,t))}
                        </div>
                    `:q}
                </div>
            </ha-card>
        `}static get styles(){return a`
            :host { display: block; }
            .glow-svg { position: absolute; width: 0; height: 0; }

            .wrap {
                padding: 16px 20px;
                position: relative;
                background:
                    radial-gradient(ellipse 70% 60% at 50% 25%, rgba(141,200,146,0.06) 0%, transparent 100%),
                    radial-gradient(circle at 2px 2px, rgba(128,128,128,0.05) 0.7px, transparent 0.7px);
                background-size: 100% 100%, 50px 50px;
                font-family: 'Segoe UI','Roboto',sans-serif;
                color: var(--primary-text-color, #e0e0e0);
                min-height: 108px;
                overflow: hidden;
            }

            /* Hero layout */
            .hero {
                display: flex;
                align-items: center;
                gap: 20px;
            }

            /* Icon area */
            .ev-icon-area {
                position: relative;
                width: 90px; height: 90px;
                flex-shrink: 0;
            }
            .ev-icon-area svg { width: 100%; height: 100%; }

            /* Glow ring */
            .glow-ring {
                fill: none;
                stroke: #8DC892;
                stroke-width: 6;
                filter: url(#ev-glow-soft);
                transition: opacity 0.6s ease;
            }
            .state-charging .glow-ring {
                animation: pulse-ring 2s ease-in-out infinite;
            }
            @keyframes pulse-ring {
                0%, 100% { stroke-width: 6; opacity: 0.5; }
                50% { stroke-width: 10; opacity: 0.7; }
            }

            .ring-bg {
                fill: none;
                stroke: rgba(141,200,146,0.12);
                stroke-width: 3;
            }
            .ring-fill {
                fill: rgba(141,200,146,0.07);
            }

            .charger-icon {
                stroke: #8DC892;
                fill: none;
                stroke-width: 1.8;
                stroke-linecap: round;
                stroke-linejoin: round;
                opacity: 0.7;
                transition: opacity 0.4s ease;
            }
            .state-disconnected .charger-icon { stroke: #666; opacity: 0.35; }
            .state-disconnected .ring-bg { stroke: rgba(100,100,100,0.12); }
            .state-disconnected .ring-fill { fill: rgba(100,100,100,0.05); }
            .state-disconnected .glow-ring { stroke: #666; }

            .lightning-bolt {
                fill: #8DC892;
                transition: opacity 0.4s ease;
                filter: url(#ev-glow);
            }
            .state-charging .lightning-bolt {
                animation: bolt-pulse 1.5s ease-in-out infinite;
            }
            @keyframes bolt-pulse {
                0%, 100% { opacity: 0.9; }
                50% { opacity: 0.5; }
            }

            .indicator-dot {
                fill: #666;
                opacity: 0.3;
                transition: fill 0.4s ease, opacity 0.4s ease;
            }
            .state-connected .indicator-dot { fill: #8DC892; opacity: 0.5; }
            .state-charging .indicator-dot {
                fill: #8DC892; opacity: 1;
                animation: dot-blink 1s ease-in-out infinite;
            }
            @keyframes dot-blink {
                0%, 100% { opacity: 1; }
                50% { opacity: 0.3; }
            }

            /* Metrics column */
            .metrics-col {
                flex: 1; min-width: 0;
                display: flex;
                flex-direction: column;
                gap: 2px;
            }
            .metric-row {
                display: flex;
                justify-content: space-between;
                align-items: baseline;
                gap: 8px;            /* #523/#524 follow-up: keep label + value
                                        apart when the column shrink-wraps in
                                        the centered hero ("StatusDisconnected") */
                padding: 2px 0;
            }
            .metric-label {
                font-size: 11px;
                color: var(--secondary-text-color, #999);
                font-weight: 500;
            }
            .metric-value {
                font-size: 12px;
                font-weight: 600;
                font-variant-numeric: tabular-nums;
                color: var(--primary-text-color, #e0e0e0);
            }

            .status-value { font-size: 13px; font-weight: 700; font-variant-numeric: tabular-nums; }
            .status-value.charging { color: #8DC892; text-shadow: 0 0 8px rgba(141,200,146,0.4); }
            .status-value.connected { color: #8DC892; }
            .status-value.disconnected { color: var(--secondary-text-color, #999); }

            .power-row .metric-value {
                font-size: 16px;
                font-weight: 700;
                color: #8DC892;
                text-shadow: 0 0 6px rgba(141,200,146,0.3);
            }

            .solar-share-value { color: #ff9800 !important; }

            .strategy-value {
                font-size: 11px;
                color: #8DC892; opacity: 0.7;
                font-weight: 500;
                white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
            }

            /* Bottom bar */
            .bottom-bar {
                display: flex;
                align-items: center;
                gap: 8px;
                margin-top: 10px;
                flex-wrap: wrap;
            }
            .chip {
                display: inline-flex; align-items: center; gap: 4px;
                background: var(--secondary-background-color, rgba(255,255,255,0.06));
                border: 1px solid var(--divider-color, rgba(255,255,255,0.12));
                border-radius: 12px;
                padding: 3px 10px;
                font-size: 11px; font-weight: 500;
                color: var(--primary-text-color, #e0e0e0);
                font-variant-numeric: tabular-nums;
            }
            .chip-label { color: var(--secondary-text-color, #888); }
            .cost-chip-value { color: #f06292; }

            /* Per-charger sections */
            .charger-sections {
                margin-top: 16px;
                display: flex;
                flex-direction: column;
                gap: 12px;
            }
            .charger-section {
                background: var(--secondary-background-color, rgba(255,255,255,0.06));
                border: 1px solid var(--divider-color, rgba(255,255,255,0.12));
                border-radius: 12px;
                padding: 12px 14px;
            }
            .charger-header {
                display: flex; align-items: center; gap: 8px;
                margin-bottom: 10px;
            }
            .charger-dot {
                width: 8px; height: 8px;
                border-radius: 50%;
                flex-shrink: 0;
            }
            .charger-name {
                flex: 1; font-weight: 600; font-size: 0.95em;
                color: var(--primary-text-color, #e0e0e0);
            }
            .charger-status {
                font-size: 0.8em; font-weight: 500;
                text-transform: uppercase; letter-spacing: 0.05em;
                color: var(--secondary-text-color, #999);
            }
            .charger-set {
                font-weight: 400; opacity: 0.85;
                font-variant-numeric: tabular-nums;
            }
            .charger-body {
                display: flex; align-items: center; gap: 12px;
            }
            .charger-soc {
                flex-shrink: 0; width: 44px; text-align: center;
            }
            .soc-label {
                display: block;
                font-size: 10px; color: var(--secondary-text-color, #999);
                margin-top: 2px;
                text-transform: uppercase; letter-spacing: 0.05em;
            }
            .charger-metrics {
                flex: 1;
                display: flex; flex-direction: column; gap: 2px;
            }
            .cm-row {
                display: flex; justify-content: space-between; align-items: baseline;
                padding: 2px 0;
            }
            .cm-label { font-size: 11px; color: var(--secondary-text-color, #999); font-weight: 500; }
            .cm-value {
                font-size: 12px; font-weight: 600;
                color: var(--primary-text-color, #e0e0e0);
                font-variant-numeric: tabular-nums;
            }
            .charger-settings {
                display: flex; align-items: center; gap: 6px;
                margin-top: 8px; padding-top: 8px;
                border-top: 1px solid var(--divider-color, rgba(255,255,255,0.12));
                flex-wrap: wrap;
            }
            /* Help mode: switch to a vertical list so each tile gets a
               one-line description below it. Compact when off. */
            .charger-settings.help-mode {
                flex-direction: column; align-items: stretch; gap: 4px;
            }
            .setting-cell { display: flex; align-items: center; gap: 6px; }
            .charger-settings.help-mode .setting-cell {
                flex-direction: column; align-items: flex-start; gap: 2px;
            }
            .setting-help {
                font-size: 11px;
                line-height: 1.3;
                color: var(--secondary-text-color, #888);
                opacity: 0.85;
                font-style: italic;
                padding-left: 22px;
            }
            .ev-help-toggle {
                cursor: pointer;
                color: var(--secondary-text-color, #999);
                opacity: 0.6;
                margin-left: auto;
                flex-shrink: 0;
                transition: opacity 0.15s, color 0.15s;
            }
            .ev-help-toggle:hover { opacity: 1; }
            .ev-help-toggle.on { color: #8DC892; opacity: 1; }
            .charger-settings.help-mode .ev-help-toggle { align-self: flex-end; }
            .setting-item {
                display: flex; align-items: center; gap: 3px;
                font-size: 11px; color: var(--secondary-text-color, #999);
            }
            .setting-item.clickable { cursor: pointer; }
            .setting-label { font-size: 11px; color: var(--secondary-text-color, #999); }
            .setting-value { font-size: 12px; font-weight: 600; color: var(--primary-text-color, #e0e0e0); }
            .setting-toggle {
                font-size: 11px; font-weight: 700;
                padding: 1px 6px;
                border-radius: 6px;
                cursor: pointer;
                user-select: none;
                transition: background 0.2s, color 0.2s;
            }
            .setting-toggle.on  { background: rgba(121,134,203,0.25); color: #7986CB; }
            .setting-toggle.off { background: rgba(100,100,100,0.15); color: #666; }
            .setting-toggle:hover { opacity: 0.8; }

            /* Charge Target group (#235) */
            .charge-target-group {
                margin-top: 8px;
                padding: 10px 12px;
                border: 1px solid var(--divider-color, rgba(255,255,255,0.12));
                border-radius: 10px;
                background: rgba(255,255,255,0.025);
            }
            .ct-title {
                font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em;
                color: var(--secondary-text-color, #999);
                display: flex; align-items: center; gap: 5px;
                margin-bottom: 4px;
            }
            .ct-range { color: #5BC8D8; font-weight: 600; text-transform: none; letter-spacing: 0; }
            .ct-spacer { margin-left: auto; }
            /* Dual-handle charge-target range slider (#245) */
            .range-wrap { padding: 6px 8px 10px; }
            .range-labels {
                display: flex; justify-content: space-between;
                font-size: 12px; color: var(--primary-text-color, #e0e0e0);
                margin-bottom: 10px;
            }
            .range-labels b { font-variant-numeric: tabular-nums; }
            .range-track {
                position: relative; height: 6px; border-radius: 3px;
                background: rgba(255,255,255,0.14); margin: 6px 9px;
                touch-action: none;
            }
            .range-fill {
                position: absolute; top: 0; height: 100%; border-radius: 3px;
                background: linear-gradient(90deg, #8DC892, #ff9800);
            }
            .range-handle {
                position: absolute; top: 50%; width: 18px; height: 18px;
                border-radius: 50%; transform: translate(-50%, -50%);
                background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.5);
                cursor: grab; touch-action: none;
            }
            .range-handle:active { cursor: grabbing; }
            .range-handle-min { border: 3px solid #8DC892; }
            .range-handle-max { border: 3px solid #ff9800; }
            .ct-row {
                display: flex; align-items: center; min-height: 32px;
            }
            .ct-row + .ct-row { border-top: 1px solid rgba(255,255,255,0.06); }
            .ct-row.clickable { cursor: pointer; }
            /* Tariff is nested under "Overnight grid charging" — it refines WHEN
               grid charging happens, not WHETHER (#247 UX). */
            .ct-subrow { padding-left: 14px; border-left: 2px solid rgba(141,200,146,0.35); margin-left: 2px; }
            .ct-subrow .ct-label { color: var(--secondary-text-color, #b5b5b5); }
            .ct-subhint {
                padding: 4px 0 4px 16px; margin-left: 2px;
                border-left: 2px solid rgba(141,200,146,0.18);
                font-size: 11px; line-height: 1.35; color: var(--secondary-text-color, #999);
                display: flex; flex-direction: column; gap: 2px;
            }
            .ct-hint-row { display: flex; gap: 6px; align-items: baseline; }
            .ct-hint-label {
                color: var(--secondary-text-color, #b5b5b5);
                font-weight: 600; flex-shrink: 0;
                min-width: 64px; text-align: right;
            }
            .ct-hint-text { color: var(--secondary-text-color, #999); }
            .ct-hint-extra { padding-top: 2px; border-top: 1px dashed rgba(255,255,255,0.05); }
            /* Cheap-window timing kept visible when help is off — too
               useful to hide behind the (?). One small line. */
            .ct-cheap-hint {
                padding: 3px 0 0 16px; margin-left: 2px;
                border-left: 2px solid rgba(141,200,146,0.18);
                font-size: 11px; color: var(--secondary-text-color, #999);
                display: flex; gap: 6px; align-items: baseline;
            }
            .ct-cheap-hint .ct-hint-label {
                min-width: auto; text-align: left;
            }
            .ct-label { font-size: 12px; color: var(--primary-text-color, #e0e0e0); }
            .ct-ctl { margin-left: auto; display: flex; align-items: center; gap: 7px; }
            .ct-time {
                font-size: 12px; font-weight: 600; font-variant-numeric: tabular-nums;
                color: var(--primary-text-color, #e0e0e0);
            }
            .ct-warn {
                display: flex; align-items: center; gap: 6px;
                font-size: 12px; color: #f06292; padding: 5px 0 2px;
            }
            /* 12h EV plan strip (#282, readability pass #464) */
            .plan-strip {
                margin: 8px 0 2px; padding: 4px 0 2px;
                border-top: 1px dashed rgba(255,255,255,0.06);
            }
            .strip-title {
                display: flex; align-items: center; gap: 5px;
                font-size: 11px; font-weight: 600;
                color: var(--secondary-text-color, #aaa);
                letter-spacing: 0.3px; margin-bottom: 4px;
            }
            .strip-svg {
                width: 100%; height: 16px; display: block;
                border-radius: 3px; overflow: hidden;
            }
            .strip-axis {
                position: relative; height: 12px; margin-top: 2px;
                font-size: 10px; color: var(--secondary-text-color, #888);
            }
            .strip-axis .tick {
                position: absolute; transform: translateX(-50%);
                font-variant-numeric: tabular-nums; white-space: nowrap;
            }
            .strip-legend {
                display: flex; gap: 6px 11px; flex-wrap: wrap;
                font-size: 10.5px; color: var(--primary-text-color, #ddd);
                margin-top: 5px;
            }
            .strip-legend span {
                display: inline-flex; align-items: center; gap: 5px;
            }
            .strip-legend i {
                width: 11px; height: 11px; border-radius: 2px;
                display: inline-block; flex: none;
            }
            /* Tariff overlays render as a thin top line on the strip — mirror
               that shape in the legend so they read as the top line, not a
               full segment (#464). */
            .strip-legend i.line {
                height: 4px; border-radius: 1px;
            }
            .strip-help { margin-top: 6px; }
            /* #355 — split affordance shown only when the two range
               handles share a value. Sits on top of the stacked
               handles; tapping it drops Min by one step so the
               handles become individually grabbable again. */
            .range-split {
                position: absolute; top: 50%;
                transform: translate(-50%, -50%);
                width: 22px; height: 22px; border-radius: 50%;
                display: flex; align-items: center; justify-content: center;
                background: rgba(0,0,0,0.55);
                color: #fff;
                cursor: pointer;
                box-shadow: 0 1px 3px rgba(0,0,0,0.5);
                pointer-events: auto;
                z-index: 2;
            }
            .range-split:hover { background: rgba(0,0,0,0.75); }
            .ct-val {
                background: rgba(141,200,146,0.14); color: #8DC892;
                border: 1px solid rgba(141,200,146,0.35);
                border-radius: 8px; padding: 3px 11px; font-weight: 600;
                font-variant-numeric: tabular-nums; min-width: 42px; text-align: center;
            }
            .ct-val.clickable { cursor: pointer; }
            .ct-unit {
                appearance: none; -webkit-appearance: none;
                background-color: var(--secondary-background-color, rgba(255,255,255,0.07));
                /* explicit caret — appearance:none drops the native arrow, which made
                   this look like a static label rather than a kWh/% toggle (#245) */
                background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath fill='%23bbbbbb' d='M7 10l5 5 5-5z'/%3E%3C/svg%3E");
                background-repeat: no-repeat;
                background-position: right 3px center;
                background-size: 14px;
                color: var(--primary-text-color, #e0e0e0);
                border: 1px solid var(--divider-color, rgba(255,255,255,0.12));
                border-radius: 8px; padding: 4px 20px 4px 8px;
                font-size: 12px; font-weight: 600; cursor: pointer;
            }
            .ct-unit-static {
                font-size: 12px; font-weight: 600;
                color: var(--secondary-text-color, #999); padding: 4px 2px;
            }
            /* #277 Phase B.2 — Charge mode selector. Wider than ct-unit
               (multi-word labels) and aligned right inside the row's
               .ct-ctl cell. Same caret + chrome as ct-unit so the two
               selectors visually rhyme. */
            .ct-mode-select {
                appearance: none; -webkit-appearance: none;
                background-color: var(--secondary-background-color, rgba(255,255,255,0.07));
                background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath fill='%23bbbbbb' d='M7 10l5 5 5-5z'/%3E%3C/svg%3E");
                background-repeat: no-repeat;
                background-position: right 6px center;
                background-size: 14px;
                color: var(--primary-text-color, #e0e0e0);
                border: 1px solid var(--divider-color, rgba(255,255,255,0.12));
                border-radius: 8px;
                padding: 4px 24px 4px 10px;
                font-size: 12px; font-weight: 600;
                cursor: pointer;
                max-width: 200px;
            }
            .ct-sw {
                width: 38px; height: 22px; border-radius: 12px;
                position: relative; cursor: pointer; flex-shrink: 0;
                transition: background 0.18s;
            }
            .ct-sw.on { background: #8DC892; }
            .ct-sw.off { background: rgba(255,255,255,0.16); }
            .ct-knob {
                position: absolute; top: 2px; left: 2px;
                width: 18px; height: 18px; border-radius: 50%;
                background: #fff; box-shadow: 0 1px 2px rgba(0,0,0,0.4);
                transition: left 0.18s;
            }
            .ct-sw.on .ct-knob { left: 18px; }

            @media (max-width: 400px) {
                /* Match the Battery tab exactly: stack the hero, keep the base
                   align-items:center so the metrics sit as a content-width block with
                   label-left / value-right rows (not stretched edge-to-edge). */
                .hero { flex-direction: column; gap: 12px; }
                .ev-icon-area { width: 80px; height: 80px; }
            }
        `}getCardSize(){return this._chargers.length>=1?3+2*this._chargers.length:3}static getStubConfig(){return{}}},{type:"sem-ev-status-card",name:"SEM EV Status",description:"Lumina-styled EV charging hero card with per-charger intelligence and settings"});const dt=["sensor.sem_solar_power","sensor.sem_battery_soc","sensor.sem_autarky_rate","sensor.sem_ev_power","sensor.sem_energy_optimization_score","sensor.sem_energy_tip","sensor.sem_best_surplus_window","sensor.sem_forecast_remaining_today_kwh","sensor.sem_current_vs_peak_percentage","sensor.sem_consecutive_peak_15min","sensor.sem_target_peak_limit","sensor.sem_daily_co2_avoided","sensor.sem_lifetime_co2_avoided"];$e("sem-home-status-card",class extends ke{static get watchedEntities(){return dt}setConfig(e){super.setConfig(e),this._prefix=e.entity_prefix||"sensor.sem_"}_val(e,t=0){const i=this._hass?.states[`${this._prefix}${e}`];return i&&"unavailable"!==i.state&&"unknown"!==i.state?parseFloat(i.state)??t:t}_valStr(e){const t=this._hass?.states[`${this._prefix}${e}`];return t&&"unavailable"!==t.state&&"unknown"!==t.state?t.state:""}_scoreColor(e){return e>=80?"#8DC892":e>=50?"#ff9800":"#f44336"}_peakColor(e){return e>90?"#f44336":e>70?"#ff9800":"#8DC892"}_peakStatusKey(e){return e>90?"peak_critical":e>70?"peak_warning":"peak_safe"}_renderChip(e,t,i){return W`
            <div class="chip">
                <ha-icon icon="${e}" style="--mdc-icon-size:16px;color:${t}"></ha-icon>
                <span class="chip-val">${i}</span>
            </div>
        `}render(){if(!this._config||!this._hass)return q;const e=this._val("solar_power"),t=this._val("battery_soc"),i=this._val("autarky_rate"),s=this._val("ev_power"),r=this._val("energy_optimization_score"),a=this._scoreColor(r),o=this._valStr("energy_tip"),n=this._valStr("best_surplus_window")||"—",l=this._val("forecast_remaining_today_kwh").toFixed(1),c=this._val("current_vs_peak_percentage"),d=this._peakColor(c),p=this._val("consecutive_peak_15min").toFixed(1),h=this._val("target_peak_limit").toFixed(1),_=this._val("daily_co2_avoided").toFixed(2),g=this._val("lifetime_co2_avoided").toFixed(1);return W`
            <div class="wrap">

                <!-- 1. Status Chips -->
                <div class="chips-row">
                    ${this._renderChip("mdi:solar-power","#ff9800",ge(e))}
                    ${this._renderChip("mdi:battery","#4db6ac",`${t.toFixed(0)}%`)}
                    ${this._renderChip("mdi:leaf","#8DC892",`${i.toFixed(0)}%`)}
                    ${this._renderChip("mdi:car-electric","#8DC892",s>0?ge(s):"—")}
                    <div class="chip">
                        <ha-icon icon="mdi:speedometer" style="--mdc-icon-size:16px;color:${a}"></ha-icon>
                        <span class="chip-val">${r.toFixed(0)}</span>
                    </div>
                </div>

                <div class="divider"></div>

                <!-- 2. Smart Tip -->
                <div class="tip-section" style="opacity:${o?"1":"0"};pointer-events:${o?"auto":"none"}">
                    <ha-icon icon="mdi:lightbulb-on-outline"
                             style="--mdc-icon-size:20px;color:#ff9800"></ha-icon>
                    <div class="tip-content">
                        <span class="section-label">${this._t("smart_tip")}</span>
                        <span class="tip-primary">${o||""}</span>
                        <span class="tip-secondary">
                            ${this._t("best_window")}: ${n} &middot; ${this._t("surplus")}: ${l} kWh
                        </span>
                    </div>
                </div>
                <div class="divider" style="opacity:${o?"1":"0"}"></div>

                <!-- 3. Peak Load -->
                <div class="section-label">${this._t("peak_load")}</div>
                <div class="peak-row">
                    <div class="peak-icon-wrap">
                        <ha-icon icon="mdi:flash-alert"
                                 style="--mdc-icon-size:22px;color:#ff9800"></ha-icon>
                        <span class="peak-pct" style="color:${d}">${c.toFixed(0)}%</span>
                    </div>
                    <div class="peak-text-wrap">
                        <span class="peak-detail">${p} / ${h} kW (${c.toFixed(0)}%)</span>
                        <span class="peak-status-badge" style="color:${d};border-color:${d}">
                            ${this._t(this._peakStatusKey(c))}
                        </span>
                    </div>
                </div>

                <div class="divider"></div>

                <!-- 5. Environmental Impact -->
                <div class="section-label">${this._t("environmental_impact")}</div>
                <div class="env-row">
                    <div class="env-chip">
                        <ha-icon icon="mdi:leaf"
                                 style="--mdc-icon-size:18px;color:#8DC892"></ha-icon>
                        <div class="env-chip-content">
                            <span class="env-chip-val">${_} kg</span>
                            <span class="env-chip-label">${this._t("co2_today")}</span>
                        </div>
                    </div>
                    <div class="env-chip">
                        <ha-icon icon="mdi:tree"
                                 style="--mdc-icon-size:18px;color:#8DC892"></ha-icon>
                        <div class="env-chip-content">
                            <span class="env-chip-val">${g} kg</span>
                            <span class="env-chip-label">${this._t("co2_lifetime")}</span>
                        </div>
                    </div>
                </div>

            </div>
        `}static get styles(){return a`
            :host { display: block; }

            .wrap {
                padding: 16px 20px;
                position: relative;
                font-family: 'Segoe UI','Roboto',sans-serif;
                color: var(--primary-text-color, #e0e0e0);
                background:
                    radial-gradient(ellipse 70% 60% at 50% 25%, rgba(91,200,216,0.06) 0%, transparent 100%),
                    radial-gradient(circle at 2px 2px, rgba(128,128,128,0.05) 0.7px, transparent 0.7px);
                background-size: 100% 100%, 50px 50px;
            }

            /* ── Section label ── */
            .section-label {
                font-size: 11px;
                font-weight: 600;
                text-transform: uppercase;
                letter-spacing: 0.6px;
                color: var(--secondary-text-color, #999);
                margin-bottom: 6px;
            }

            /* ── Divider ── */
            .divider {
                height: 1px;
                background: var(--divider-color, rgba(255,255,255,0.12));
                margin: 12px 0;
            }

            /* ─────────────────── 1. Chips ─────────────────── */
            .chips-row {
                display: flex;
                gap: 6px;
                overflow-x: auto;
                padding-bottom: 4px;
                scrollbar-width: none;
                -ms-overflow-style: none;
            }
            .chips-row::-webkit-scrollbar { display: none; }

            .chip {
                display: inline-flex; align-items: center; gap: 4px;
                padding: 4px 10px;
                border-radius: 12px;
                border: 1px solid var(--divider-color, rgba(255,255,255,0.12));
                background: var(--secondary-background-color, rgba(255,255,255,0.06));
                white-space: nowrap;
                flex-shrink: 0;
                backdrop-filter: blur(16px) saturate(160%);
                -webkit-backdrop-filter: blur(16px) saturate(160%);
            }
            .chip-val {
                font-size: 12px;
                font-weight: 600;
                font-variant-numeric: tabular-nums;
            }

            /* ─────────────────── 2. Tip ─────────────────── */
            .tip-section {
                display: flex; gap: 10px; align-items: flex-start;
                padding: 10px 12px;
                border-radius: 12px;
                background: rgba(255,152,0,0.06);
                border: 1px solid rgba(255,152,0,0.20);
            }
            .tip-section ha-icon { flex-shrink: 0; margin-top: 1px; }
            .tip-content { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
            .tip-primary {
                font-size: 13px; font-weight: 500; line-height: 1.4;
            }
            .tip-secondary {
                font-size: 11px;
                color: var(--secondary-text-color, #999);
                line-height: 1.3;
            }

            /* ─────────────────── 3. Peak ─────────────────── */
            .peak-row {
                display: flex; align-items: center; gap: 10px;
            }
            .peak-icon-wrap {
                display: flex; align-items: center; gap: 6px;
                flex-shrink: 0;
            }
            .peak-pct {
                font-size: 22px; font-weight: 700;
                font-variant-numeric: tabular-nums;
                line-height: 1;
            }
            .peak-text-wrap {
                display: flex; flex-direction: column; gap: 2px;
                min-width: 0;
            }
            .peak-detail {
                font-size: 12px;
                color: var(--secondary-text-color, #999);
                white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
            }
            .peak-status-badge {
                display: inline-block;
                font-size: 11px; font-weight: 600;
                text-transform: uppercase; letter-spacing: 0.4px;
                padding: 2px 7px;
                border-radius: 8px;
                border: 1px solid;
                align-self: flex-start;
            }

            /* ─────────────────── 5. Environmental ─────────────────── */
            .env-row {
                display: flex; gap: 8px; flex-wrap: wrap;
            }
            .env-chip {
                display: flex; align-items: center; gap: 6px;
                padding: 6px 12px;
                border-radius: 12px;
                border: 1px solid rgba(141,200,146,0.25);
                background: rgba(141,200,146,0.06);
                flex: 1; min-width: 120px;
            }
            .env-chip ha-icon { flex-shrink: 0; }
            .env-chip-content { display: flex; flex-direction: column; gap: 0; }
            .env-chip-val {
                font-size: 13px; font-weight: 600;
                font-variant-numeric: tabular-nums;
            }
            .env-chip-label {
                font-size: 11px;
                color: var(--secondary-text-color, #999);
                text-transform: uppercase; letter-spacing: 0.3px;
            }

            @media (max-width: 400px) {
                .env-row { flex-direction: column; }
            }
        `}getCardSize(){return 5}static getStubConfig(){return{entity_prefix:"sensor.sem_"}}},{type:"custom:sem-home-status-card",name:"SEM Home Status Card",description:"Consolidated status panel for the SEM Home tab",preview:!1});const pt="sensor.sem_tariff_current_import_rate",ht={negative:{color:"#4db6ac",key:"price_negative"},very_cheap:{color:"#8DC892",key:"very_cheap"},cheap:{color:"#8DC892",key:"cheap"},normal:{color:"#ff9800",key:"normal"},expensive:{color:"#f06292",key:"expensive"},very_expensive:{color:"#e53935",key:"very_expensive"}};$e("sem-price-card",class extends ke{constructor(){super(),this._boundVisibility=()=>{document.hidden||this.requestUpdate()}}connectedCallback(){super.connectedCallback(),document.addEventListener("visibilitychange",this._boundVisibility)}disconnectedCallback(){super.disconnectedCallback(),document.removeEventListener("visibilitychange",this._boundVisibility)}setConfig(e){super.setConfig(e),this._entity=e.entity||pt,this._compact=!!e.compact}set hass(e){this._hass=e;const t=e?.states[this._entity],i=t?.attributes||{},s=[t?.state,i.price_level,i.next_cheap_start,(i.upcoming||[]).length,this._lang].join("|"),r="function"==typeof semLocalize;(s!==this._lastKey||r&&!this._localizeReady)&&(this._lastKey=s,this._lang=e?.language,this._localizeReady=r,this.requestUpdate())}get hass(){return this._hass}_hm(e){if(!e)return null;const t=this._hass?.config?.time_zone||void 0;try{return new Date(e).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit",timeZone:t})}catch(e){return null}}_levelInfo(e){return ht[e]||{color:"#9e9e9e",key:"normal"}}render(){if(!this._hass||!this._config)return q;const e=this._hass.states[this._entity];if(!e||"unavailable"===e.state||"unknown"===e.state)return W`<ha-card><div class="wrap empty">${this._t("current_electricity_price")}: —</div></ha-card>`;const t=e.attributes||{};if(!1===t.is_dynamic)return this.style.display="none",q;this.style.display="";const i=parseFloat(e.state),s=t.currency||"",r=this._levelInfo(t.price_level),a=e=>null==e||isNaN(e)?"—":Number(e).toFixed(2),o=Array.isArray(t.upcoming)?t.upcoming:[],n=this._hm(t.next_cheap_start),l=this._hm(t.next_cheap_end);return this._compact?W`
                <ha-card>
                    <div class="chip-row">
                        <span class="chip-title">${this._t("current_electricity_price")}</span>
                        <span class="chip-price" style="color:${r.color}">${a(i)}</span>
                        <span class="chip-unit">${s}/kWh</span>
                        <span class="chip-badge" style="background:${r.color}22;color:${r.color};border-color:${r.color}55">
                            ${this._t(r.key)}
                        </span>
                        ${n?W`<span class="chip-next">${this._t("price_next_cheap")}: <b style="color:#8DC892">${n}</b></span>`:q}
                    </div>
                </ha-card>
            `:W`
            <ha-card>
                <div class="wrap">
                    <div class="head">
                        <span class="title">${this._t("current_electricity_price")}</span>
                        ${t.provider&&"unknown"!==t.provider?W`<span class="prov">${t.provider}</span>`:q}
                    </div>
                    <div class="now">
                        <span class="price" style="color:${r.color}">${a(i)}</span>
                        <span class="unit">${s}/kWh</span>
                        <span class="badge" style="background:${r.color}22;color:${r.color};border-color:${r.color}55">
                            ${this._t(r.key)}
                        </span>
                    </div>
                    <div class="summary">
                        <span>${this._t("today")}: <b>min ${a(t.today_min)}</b> · avg ${a(t.today_avg)} · <b>max ${a(t.today_max)}</b></span>
                        ${n?W`<span class="cheap">${this._t("price_next_cheap")}: <b>${n}${l?"–"+l:""}</b></span>`:q}
                    </div>
                    ${o.length>=2?this._renderStrip(o):q}
                </div>
            </ha-card>
        `}_renderStrip(e){const t=Date.now(),i=e.map(e=>({t:new Date(e.t).getTime(),price:e.price,level:e.level})).filter(e=>!isNaN(e.t)).sort((e,t)=>e.t-t.t).filter(e=>e.t>=t-36e5).slice(0,24);if(i.length<2)return q;const s=i.map(e=>e.price),r=Math.min(...s),a=Math.max(...s)-r||1,o=i.length,n=(320-2*(o-1))/o,l=i.map((e,i)=>{const s=6+52*((e.price-r)/a),o=i*(n+2),l=64-s,c=this._levelInfo(e.level).color,d=e.t<=t&&t<e.t+36e5;return j`<rect x="${o}" y="${l}" width="${n}" height="${s}" rx="1.5"
                fill="${c}" opacity="${d?"1":"0.65"}"
                stroke="${d?"#fff":"none"}" stroke-width="${d?"1":"0"}"/>`}),c=i.map((e,t)=>{if(t%6!=0)return q;const i=t*(n+2)+n/2,s=new Date(e.t).getHours();return j`<text x="${i}" y="${75}" text-anchor="middle"
                fill="var(--secondary-text-color,#999)" font-size="9">${String(s).padStart(2,"0")}</text>`});return W`
            <svg class="strip" viewBox="0 0 ${320} ${78}" width="100%" preserveAspectRatio="none">
                ${l}${c}
            </svg>
        `}getCardSize(){return 2}static getStubConfig(){return{entity:pt}}static get styles(){return a`
            ha-card { background: var(--ha-card-background, var(--card-background-color)); }
            .wrap { padding: 12px 14px; }
            .wrap.empty { color: var(--secondary-text-color,#999); }
            .head { display: flex; align-items: baseline; gap: 8px; }
            .title { font-size: 13px; font-weight: 600; color: var(--primary-text-color,#e0e0e0); }
            .prov { margin-left: auto; font-size: 12px; color: var(--secondary-text-color,#999); text-transform: capitalize; }
            .now { display: flex; align-items: baseline; gap: 8px; margin: 4px 0 6px; }
            .price { font-size: 30px; font-weight: 700; font-variant-numeric: tabular-nums; line-height: 1; }
            .unit { font-size: 12px; color: var(--secondary-text-color,#999); }
            .badge { margin-left: auto; font-size: 12px; font-weight: 600; padding: 2px 9px;
                     border-radius: 10px; border: 1px solid; text-transform: capitalize; }
            .summary { display: flex; flex-wrap: wrap; gap: 4px 14px; font-size: 12px;
                       color: var(--secondary-text-color,#aaa); margin-bottom: 8px; }
            .summary b { color: var(--primary-text-color,#e0e0e0); font-variant-numeric: tabular-nums; }
            .summary .cheap b { color: #8DC892; }
            .strip { display: block; overflow: visible; }
            .static-note { font-size: 12px; color: var(--secondary-text-color,#999); padding-top: 2px; }
            /* Compact chip (#257, compact: true) — one row, glance-only. */
            .chip-row {
                display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
                padding: 8px 14px;
            }
            .chip-title { font-size: 12px; font-weight: 600; color: var(--primary-text-color,#e0e0e0); }
            .chip-price { font-size: 17px; font-weight: 700; font-variant-numeric: tabular-nums; line-height: 1; }
            .chip-unit { font-size: 12px; color: var(--secondary-text-color,#999); }
            .chip-badge { font-size: 11px; font-weight: 600; padding: 1px 8px;
                          border-radius: 9px; border: 1px solid; text-transform: capitalize; }
            .chip-next { margin-left: auto; font-size: 12px; color: var(--secondary-text-color,#aaa); }
            .chip-next b { font-variant-numeric: tabular-nums; }
        `}},{type:"custom:sem-price-card",name:"SEM Price Card",description:"Dynamic electricity price: current price, level, today range, next cheap window, and an hourly price strip (#257)",preview:!1});const _t=[{id:"info",icon:"mdi:information-outline",color:"#96CAEE",titleKey:"system_info",subtitleFn:e=>{const t=e._val("diag_version")||"—",i=e._val("diag_grid_mode")||"—";return`v${t} · ${"combined"===i?e._t("grid_combined"):"split"===i?e._t("grid_split"):i}`}},{id:"health",icon:"mdi:heart-pulse",color:"#8DC892",titleKey:"health_overview",subtitleFn:e=>`${e._valNum("solar_power").toFixed(0)}W solar · SOC ${e._valNum("battery_soc").toFixed(0)}%`},{id:"diag",icon:"mdi:bug-outline",color:"#ff9800",titleKey:"diagnostics",subtitleFn:()=>""}],gt=[{key:"solar_power",icon:"mdi:solar-power",color:"#ff9800",suffix:"W"},{key:"grid_power",icon:"mdi:transmission-tower",color:"#488fc2",suffix:"W"},{key:"battery_soc",icon:"mdi:battery",color:"#4db6ac",suffix:"%"},{key:"forecast_today_kwh",icon:"mdi:weather-sunny",color:"#ff9800",suffix:"kWh"},{key:"tariff_current_import_rate",icon:"mdi:tag",color:"#96CAEE",suffix:""}],ut=["sensor.sem_diag_version","sensor.sem_diag_grid_mode","sensor.sem_diag_battery_capacity","sensor.sem_diag_update_interval","sensor.sem_diag_charger_count","sensor.sem_diag_charger_control","sensor.sem_diag_sensors_unavailable","sensor.sem_diag_ed_config","sensor.sem_solar_power","sensor.sem_grid_power","sensor.sem_battery_soc","sensor.sem_ev_power","sensor.sem_forecast_today_kwh","sensor.sem_tariff_current_import_rate","switch.sem_observer_mode","sensor.sem_home_consumption_power","sensor.sem_grid_import_power","sensor.sem_grid_export_power","sensor.sem_autarky_rate","sensor.sem_self_consumption_rate","sensor.sem_battery_power","sensor.sem_night_charging_status","sensor.sem_battery_status","sensor.sem_grid_status","sensor.sem_charging_state"];$e("sem-system-card",class extends ke{static get watchedEntities(){return ut}constructor(){super(),this._collapsed={info:!1,health:!1,diag:!0},this._copyFeedback=""}setConfig(e){super.setConfig(e),this._prefix=e.entity_prefix||"sensor.sem_"}_val(e){const t=this._hass?.states[`${this._prefix}${e}`];return t&&"unavailable"!==t.state&&"unknown"!==t.state?t.state:""}_valNum(e,t=0){const i=this._hass?.states[`${this._prefix}${e}`];return i&&"unavailable"!==i.state&&"unknown"!==i.state?parseFloat(i.state)??t:t}_switchOn(e){return"on"===this._hass?.states[`switch.sem_${e}`]?.state}_available(e){const t=this._hass?.states[e];return!(!t||"unavailable"===t.state||"unknown"===t.state)}_toggleSection(e){this._collapsed={...this._collapsed,[e]:!this._collapsed[e]},this.requestUpdate()}_copyDiagnostics(){const e=this._val("diag_version")||"—",t=this._val("diag_grid_mode")||"—",i=this._val("diag_charger_count")||"—",s=this._val("diag_charger_control")||"—",r=this._valNum("diag_battery_capacity"),a=`SEM ${e} | Grid: ${t} | Chargers: ${i} (${s}) | Battery: ${r>0?r.toFixed(1):"—"}kWh | Unavailable: ${this._val("diag_sensors_unavailable")||"0"}`,o=this._hass?.states?.["sensor.sem_diag_ed_config"]?.attributes?.energy_dashboard;let n;if(o){const e=e=>e||"—";n=`Solar:   pwr=${e(o.solar?.power)} [${e(o.solar?.power_source)}]  energy=${e(o.solar?.energy)}\nGrid:    pwr=${e(o.grid?.power)} [${e(o.grid?.power_source)}]  imp=${e(o.grid?.import_energy)}  exp=${e(o.grid?.export_energy)}\nBattery: pwr=${e(o.battery?.power)} [${e(o.battery?.power_source)}]  chg=${e(o.battery?.charge_energy)}  dis=${e(o.battery?.discharge_energy)}`}else n=`Config: ${this._val("diag_ed_config")||"—"}`;const l=`${a}\n${n}`;this._writeClipboard(l)}async _writeClipboard(e){const t=e=>{this._copyFeedback=this._t(e),this.requestUpdate(),setTimeout(()=>{this._copyFeedback="",this.requestUpdate()},2e3)};if(navigator?.clipboard?.writeText&&!1!==window.isSecureContext)try{return await navigator.clipboard.writeText(e),void t("copied")}catch(e){console.warn("[SEM System] modern clipboard API failed, falling back to execCommand",e)}try{const i=document.createElement("textarea");i.value=e,i.setAttribute("readonly",""),i.style.position="fixed",i.style.top="0",i.style.left="0",i.style.width="1px",i.style.height="1px",i.style.opacity="0",document.body.appendChild(i),i.focus(),i.select();const s=document.execCommand("copy");document.body.removeChild(i),s?t("copied"):(t("copy_failed"),console.error('[SEM System] execCommand("copy") returned false'))}catch(e){t("copy_failed"),console.error("[SEM System] legacy clipboard fallback threw",e)}}_renderSectionHeader(e,t){const i=this._collapsed[e.id],s=i?"rotate(-90deg)":"rotate(0deg)";return W`
            <div
                class="section-header"
                tabindex="0"
                role="button"
                aria-expanded="${!i}"
                @click=${()=>this._toggleSection(e.id)}
                @keydown=${t=>{"Enter"!==t.key&&" "!==t.key||(t.preventDefault(),this._toggleSection(e.id))}}
            >
                <ha-icon icon="${e.icon}" style="--mdc-icon-size:20px;color:${e.color}"></ha-icon>
                <span class="section-title-text">${this._t(e.titleKey)}</span>
                <span class="section-subtitle">${e.subtitleFn(this)}</span>
                <ha-icon
                    class="chevron"
                    icon="mdi:chevron-down"
                    style="--mdc-icon-size:18px;transform:${s}"
                ></ha-icon>
            </div>
        `}_renderInfoSection(e){const t=this._valNum("diag_battery_capacity"),i=this._valNum("diag_update_interval"),s=this._val("diag_charger_count")||"—",r=this._val("diag_charger_control")||"",a=r?`${s} (${r})`:s;return W`
            <div class="info-row">
                <span class="info-row-label">${this._t("version")}</span>
                <span class="info-row-value">${this._val("diag_version")||"—"}</span>
            </div>
            <div class="info-row">
                <span class="info-row-label">${this._t("grid_mode")}</span>
                <span class="info-row-value">${(()=>{const e=this._val("diag_grid_mode")||"—";return"combined"===e?this._t("grid_combined"):"split"===e?this._t("grid_split"):e})()}</span>
            </div>
            <div class="info-row">
                <span class="info-row-label">${this._t("battery_capacity")}</span>
                <span class="info-row-value">${t>0?t.toFixed(1)+" kWh":"—"}</span>
            </div>
            <div class="info-row">
                <span class="info-row-label">${this._t("update_interval")}</span>
                <span class="info-row-value">${i>0?i.toFixed(0)+" s":"—"}</span>
            </div>
            <div class="info-row">
                <span class="info-row-label">${this._t("chargers")}</span>
                <span class="info-row-value">${a}</span>
            </div>
            <div class="info-row">
                <span class="info-row-label">${this._t("unavailable_sensors")}</span>
                <span class="info-row-value">${this._val("diag_sensors_unavailable")||"0"}</span>
            </div>
        `}_renderHealthSection(e){return W`
            <div class="health-chips">
                ${gt.map(e=>{const t=`${this._prefix}${e.key}`,i=this._available(t),s=this._hass?.states[t],r=s?s.state:"—";let a=e.suffix;if("tariff_current_import_rate"===e.key){const e=s?.attributes?.currency;a=e?` ${e}/kWh`:""}return W`
                        <div class="health-chip" style="background:${i?"rgba(141,200,146,0.12)":"rgba(244,67,54,0.12)"};border:1px solid ${i?"rgba(141,200,146,0.3)":"rgba(244,67,54,0.3)"}">
                            <ha-icon icon="${e.icon}" style="--mdc-icon-size:16px;color:${e.color}"></ha-icon>
                            <span class="chip-value">${i?`${r}${a}`:"—"}</span>
                        </div>
                    `})}
            </div>
        `}_renderToggle(e,t,i){const s="on"===this._hass?.states[e]?.state;return W`
            <div class="toggle-row">
                <span class="toggle-label">${this._t(t)}</span>
                <div
                    class="toggle-track ${s?"on":""}"
                    @click=${()=>this._toggleSwitch(e)}
                >
                    <div class="toggle-thumb"></div>
                </div>
            </div>
        `}_renderDiagBlock(e,t){return W`
            <div class="diag-block">
                <span class="diag-block-label">${this._t(e)}</span>
                <span class="diag-block-text">${t}</span>
            </div>
        `}_renderDiagSection(e){const t=`Solar ${this._valNum("solar_power").toFixed(0)}W · Grid ${this._valNum("grid_power").toFixed(0)}W · Battery ${this._valNum("battery_power").toFixed(0)}W · SOC ${this._valNum("battery_soc").toFixed(0)}% · EV ${this._valNum("ev_power").toFixed(0)}W`,i=`Home ${this._valNum("home_consumption_power").toFixed(0)}W · Import ${this._valNum("grid_import_power").toFixed(0)}W · Export ${this._valNum("grid_export_power").toFixed(0)}W · Autarky ${this._valNum("autarky_rate").toFixed(0)}% · Self ${this._valNum("self_consumption_rate").toFixed(0)}%`,s=this._val("charging_state")||"—",r=this._val("night_charging_status")||"—",a=this._val("battery_status")||"—",o=this._val("grid_status")||"—",n=`${s} · ${this._t("night")}: ${r} · ${this._t("battery")}: ${a} · ${this._t("grid")}: ${o}`;return W`
            ${this._renderDiagBlock("source_sensors",t)}
            ${this._renderDiagBlock("derived_values",i)}
            ${this._renderDiagBlock("mode_status",n)}
        `}_renderSection(e,t,i){const s=this._collapsed[e.id];return W`
            <div class="section">
                ${this._renderSectionHeader(e,i)}
                <div class="section-content ${s?"":"expanded"}">
                    <div class="section-body">
                        ${t(i)}
                    </div>
                </div>
            </div>
        `}render(){if(!this._config)return q;const e=this._theme(),t=!1!==e.isDark,i=e.accent||"#42a5f5",s={info:e=>this._renderInfoSection(e),health:e=>this._renderHealthSection(e),diag:e=>this._renderDiagSection(e)};return W`
            <style>
                :host { display: block; contain: layout style paint; }
                .wrap {
                    padding: 16px 20px;
                    position: relative;
                    background: ${ye(e,pe.inverter)};
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${e.text});
                }

                /* ── Sections ── */
                .section {
                    margin-bottom: 8px;
                    border-radius: 14px;
                    background: ${e.surface};
                    border: 1px solid ${e.surfaceBorder};
                    overflow: hidden;
                    transition: border-color 0.2s;
                }
                .section:hover { border-color: ${t?"rgba(255,255,255,0.18)":"rgba(0,0,0,0.12)"}; }

                .section-header {
                    display: flex; align-items: center; gap: 8px;
                    padding: 12px 14px;
                    cursor: pointer;
                    user-select: none;
                    -webkit-user-select: none;
                    transition: background 0.15s;
                }
                .section-header:hover { background: ${e.surfaceHover}; }
                .section-title-text {
                    font-size: 14px; font-weight: 600;
                    white-space: nowrap;
                }
                .section-subtitle {
                    flex: 1;
                    font-size: 12px;
                    color: var(--secondary-text-color, ${e.textSec});
                    text-align: right;
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    margin-right: 4px;
                }
                .chevron {
                    transition: transform 0.25s ease;
                    color: var(--secondary-text-color, ${e.textSec});
                    flex-shrink: 0;
                }

                /* ── Collapsible content ── */
                .section-content {
                    max-height: 0;
                    opacity: 0;
                    overflow: hidden;
                    transition: max-height 0.3s ease, opacity 0.2s ease;
                }
                .section-content.expanded {
                    max-height: 1000px;
                    opacity: 1;
                }
                .section-body {
                    padding: 0 14px 14px;
                }

                /* ── Info rows ── */
                .info-row {
                    display: flex; align-items: center; justify-content: space-between;
                    padding: 7px 0;
                    border-bottom: 1px solid ${e.surfaceBorder};
                }
                .info-row:last-child { border-bottom: none; }
                .info-row-label {
                    font-size: 13px; font-weight: 500;
                    color: var(--secondary-text-color, ${e.textSec});
                }
                .info-row-value {
                    font-size: 13px; font-weight: 600;
                    font-variant-numeric: tabular-nums;
                }

                /* ── Health chips ── */
                .health-chips {
                    display: flex; flex-wrap: wrap; gap: 8px;
                    padding: 8px 0 4px;
                }
                .health-chip {
                    display: flex; align-items: center; gap: 6px;
                    padding: 6px 10px;
                    border-radius: 20px;
                    transition: background 0.2s, border-color 0.2s;
                }
                .chip-value {
                    font-size: 12px; font-weight: 600;
                    font-variant-numeric: tabular-nums;
                }

                /* ── Toggle ── */
                .toggle-group { padding-top: 2px; }
                .toggle-row {
                    display: flex; align-items: center; justify-content: space-between;
                    padding: 9px 0;
                    border-bottom: 1px solid ${e.surfaceBorder};
                }
                .toggle-row:last-child { border-bottom: none; }
                .toggle-label { font-size: 13px; font-weight: 500; }
                .toggle-track {
                    position: relative;
                    width: 42px; height: 24px;
                    border-radius: 12px;
                    background: ${t?"rgba(255,255,255,0.15)":"rgba(0,0,0,0.18)"};
                    cursor: pointer;
                    transition: background 0.2s;
                    flex-shrink: 0;
                }
                .toggle-track.on { background: ${i}; }
                .toggle-thumb {
                    position: absolute;
                    top: 2px; left: 2px;
                    width: 20px; height: 20px;
                    border-radius: 50%;
                    background: white;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.3);
                    transition: left 0.2s;
                }
                .toggle-track.on .toggle-thumb { left: 20px; }

                /* ── Diagnostics ── */
                .diag-block {
                    padding: 8px 0;
                    border-bottom: 1px solid ${e.surfaceBorder};
                }
                .diag-block:last-child { border-bottom: none; }
                .diag-block-label {
                    display: block;
                    font-size: 11px; font-weight: 600;
                    text-transform: uppercase;
                    letter-spacing: 0.4px;
                    color: var(--secondary-text-color, ${e.textSec});
                    margin-bottom: 3px;
                }
                .diag-block-text {
                    display: block;
                    font-size: 12px; font-weight: 500;
                    line-height: 1.5;
                    word-break: break-word;
                    font-variant-numeric: tabular-nums;
                }

                /* ── Copy button ── */
                .copy-row {
                    margin-top: 10px;
                    display: flex; flex-direction: column; align-items: center; gap: 4px;
                }
                .copy-btn {
                    display: flex; align-items: center; gap: 6px;
                    padding: 8px 18px;
                    border-radius: 10px;
                    border: 1px solid ${e.surfaceBorder};
                    background: ${e.surface};
                    color: var(--primary-text-color, ${e.text});
                    font-size: 13px; font-weight: 600;
                    font-family: inherit;
                    cursor: pointer;
                    transition: background 0.15s, border-color 0.15s;
                }
                .copy-btn:hover { background: ${e.surfaceHover}; border-color: #96CAEE; }
                .copy-btn:active { background: ${t?"rgba(255,255,255,0.15)":"rgba(0,0,0,0.08)"}; }
                .copy-feedback {
                    font-size: 11px;
                    color: #8DC892;
                    min-height: 16px;
                    transition: opacity 0.3s;
                    opacity: ${this._copyFeedback?"1":"0"};
                }

                @media (max-width: 480px) {
                    .health-chips { gap: 6px; }
                    .health-chip { padding: 5px 8px; }
                }
            </style>
            <div class="wrap">
                ${_t.map(t=>this._renderSection(t,s[t.id],e))}
                <div class="copy-row">
                    <button class="copy-btn" @click=${()=>this._copyDiagnostics()}>
                        <ha-icon icon="mdi:content-copy" style="--mdc-icon-size:16px"></ha-icon>
                        ${this._t("copy_diagnostics")}
                    </button>
                    <span class="copy-feedback">${this._copyFeedback}</span>
                </div>
            </div>
        `}getCardSize(){return 8}static getStubConfig(){return{entity_prefix:"sensor.sem_"}}},{type:"custom:sem-system-card",name:"SEM System Card",description:"Consolidated system panel for Solar Energy Management",preview:!1});const ft={now:{icon:"mdi:clock-outline",color:"#5BC8D8"},solar_peak:{icon:"mdi:weather-sunny",color:"#ff9800"},solar_end:{icon:"mdi:weather-sunset",color:"#ff9800"},cheap_start:{icon:"mdi:arrow-down-bold",color:"#8DC892"},cheap_end:{icon:"mdi:arrow-up-bold",color:"#ff9800"},expensive_start:{icon:"mdi:flash-alert",color:"#f06292"},expensive_end:{icon:"mdi:flash-off",color:"#8DC892"},night_open:{icon:"mdi:weather-night",color:"#8353d1"},night_end:{icon:"mdi:weather-sunset-up",color:"#ff9800"},ev_charge_start:{icon:"mdi:ev-station",color:"#8DC892"},ev_min_reached:{icon:"mdi:battery-charging-80",color:"#4db6ac"},ev_target_reached:{icon:"mdi:car-electric",color:"#8DC892"},ev_deadline:{icon:"mdi:clock-end",color:"#f06292"},ev_wait:{icon:"mdi:pause-circle",color:"#8353d1"},battery_full:{icon:"mdi:battery-charging-100",color:"#f06292"},battery_empty:{icon:"mdi:battery-low",color:"#4db6ac"},device_run:{icon:"mdi:power-plug",color:"#5BC8D8"},device_done:{icon:"mdi:check-circle",color:"#8DC892"}};$e("sem-today-plan-card",class extends ke{setConfig(e){super.setConfig(e),this._entity=e.entity||"sensor.sem_charging_state"}set hass(e){this._hass=e;const t=(e?.states[this._entity]?.attributes||{}).today_plan||[],i=[t.length,t[0]?.when,t.at(-1)?.when,this._lang].join("|"),s="function"==typeof semLocalize;(i!==this._lastKey||s&&!this._localizeReady)&&(this._lastKey=i,this._lang=e?.language,this._localizeReady=s,this.requestUpdate())}get hass(){return this._hass}_hm(e){if(!e)return"—";try{const t=new Date(e),i=this._hass?.config?.time_zone||void 0,s=ue(e,i),r=e=>e.toLocaleDateString("en-CA",{timeZone:i}),a=r(t),o=new Date;if(a===r(o))return s;if(a===r(new Date(o.getTime()+864e5))){return`${this._t("tomorrow")||"Tomorrow"} ${s}`}return`${t.toLocaleDateString([],{weekday:"short",timeZone:i})} ${s}`}catch(e){return"—"}}_format(e,t){let i=this._t(e);if(!i||i===e)return null;for(const[e,s]of Object.entries(t||{}))i=i.replace(new RegExp(`\\{${e}\\}`,"g"),s);return i}render(){if(!this._hass||!this._config)return q;const e=this._hass.states[this._entity],t=e?.attributes?.today_plan||[];return!Array.isArray(t)||t.length<=1?(this.style.display="none",q):(this.style.display="",W`
            <ha-card>
                <div class="wrap">
                    <div class="head">
                        <ha-icon icon="mdi:calendar-clock" style="--mdc-icon-size:16px;color:#5BC8D8"></ha-icon>
                        <span class="title">${this._t("today_plan_title")}</span>
                    </div>
                    <ul class="rows">
                        ${t.map(e=>{const t=ft[e.kind]||ft.now,i=this._format(e.label,e.values)||e.label,s=e.detail?this._format(e.detail,e.values):null;return W`
                                <li class="row ${"now"===e.kind?"now":""}">
                                    <span class="time">${this._hm(e.when)}</span>
                                    <ha-icon icon="${t.icon}" style="--mdc-icon-size:14px;color:${t.color}"></ha-icon>
                                    <div class="text">
                                        <span class="label">${i}</span>
                                        ${s?W`<span class="detail">${s}</span>`:q}
                                    </div>
                                </li>
                            `})}
                    </ul>
                </div>
            </ha-card>
        `)}static get styles(){return a`
            :host { display: block; }
            ha-card {
                background: var(--card-background-color, #1e232d);
                backdrop-filter: blur(16px) saturate(160%);
                -webkit-backdrop-filter: blur(16px) saturate(160%);
                border: 1px solid rgba(255,255,255,0.06);
                border-radius: 14px;
            }
            .wrap { padding: 12px 14px; }
            .head {
                display: flex; align-items: center; gap: 6px;
                margin-bottom: 8px;
                opacity: 0.85;
            }
            .title {
                font-size: 12px; letter-spacing: 0.04em; text-transform: uppercase;
                color: var(--primary-text-color);
            }
            .rows { list-style: none; padding: 0; margin: 0; }
            .row {
                display: grid;
                grid-template-columns: 64px 18px 1fr;
                align-items: center; gap: 10px;
                padding: 5px 0;
                font-size: 13px;
                color: var(--primary-text-color);
                border-bottom: 1px dashed rgba(255,255,255,0.04);
            }
            .row:last-child { border-bottom: none; }
            .row.now {
                background: linear-gradient(90deg, rgba(91,200,216,0.10), transparent);
                margin-left: -4px; padding-left: 4px;
                border-radius: 4px;
            }
            .time {
                font-variant-numeric: tabular-nums;
                font-weight: 600;
                color: var(--secondary-text-color);
                font-size: 12px;
            }
            .text { display: flex; flex-direction: column; min-width: 0; }
            .label { font-weight: 500; line-height: 1.2; }
            .detail {
                font-size: 11px; opacity: 0.65; line-height: 1.2;
            }
        `}},{name:"SEM Today's Plan",description:"Forward-looking schedule combining tariff, solar, and EV"});const mt=2,yt=e=>(...t)=>({_$litDirective$:e,values:t});let vt=class{constructor(e){}get _$AU(){return this._$AM._$AU}_$AT(e,t,i){this._$Ct=e,this._$AM=t,this._$Ci=i}_$AS(e,t){return this.update(e,t)}update(e,t){return this.render(...t)}};class xt extends vt{constructor(e){if(super(e),this.it=q,e.type!==mt)throw Error(this.constructor.directiveName+"() can only be used in child bindings")}render(e){if(e===q||null==e)return this._t=void 0,this.it=e;if(e===G)return e;if("string"!=typeof e)throw Error(this.constructor.directiveName+"() called with a non-string value");if(e===this.it)return this._t;this.it=e;const t=[e];return t.raw=t,this._t={_$litType$:this.constructor.resultType,strings:t,values:[]}}}xt.directiveName="unsafeHTML",xt.resultType=1;let bt=class extends xt{};bt.directiveName="unsafeSVG",bt.resultType=2;const $t=yt(bt),wt={solar:{nameKey:"solar",color:"#ff9800"},grid:{nameKey:"grid",color_import:"#488fc2",color_export:"#8353d1"},battery:{nameKey:"battery",color:"#4db6ac"},home:{nameKey:"home",color:"#5BC8D8"},ev:{nameKey:"ev_charger",color:"#8DC892"},inverter:{nameKey:"inverter",color:"#96CAEE"}};$e("sem-flow-card",class extends ke{constructor(){super(),this._lastKey="",this._animFrames={},this._currentValues={},this._compact=!1,this._visible=!0,this._deviceConfigSig="",this._devicePositions=[],this._updateTimer=null,this._resizeObserver=null,this._intersectionObserver=null,this._resizeTimeout=null,this._mode="prefix",this._prefix="sensor.sem_",this._entities=null}setConfig(e){if(this._config=e,e.entity_prefix)this._mode="prefix",this._prefix=e.entity_prefix;else{if(!e.entities)throw new Error('sem-flow-card requires either "entities" or "entity_prefix" config');this._mode="entities",this._entities=e.entities}this._showLabels=!1!==e.show_labels,this._showValues=!1!==e.show_values,this._showGlow=!1!==e.show_glow,this._showInverter=!1!==e.show_inverter,this._showEv=!1!==e.show_ev,this._showBattery=!1!==e.show_battery,this.requestUpdate()}set hass(e){this._hass,this._hass=e;const t=e?.language;if(t!==this._lang)return this._lang=t,void this.requestUpdate();const i=ve(e,this._prefix);if(i!==this._lastPVKey)return this._lastPVKey=i,void this.requestUpdate();this._visible&&(clearTimeout(this._updateTimer),this._updateTimer=setTimeout(()=>this._updateFlowsImperative(),100))}get hass(){return this._hass}firstUpdated(){this._resizeTimeout=null,this._resizeObserver=new ResizeObserver(e=>{this._resizeTimeout&&clearTimeout(this._resizeTimeout),this._resizeTimeout=setTimeout(()=>{for(const t of e){const e=t.contentRect.width<400;e!==this._compact&&(this._compact=e,this._lastKey="",this._deviceConfigSig="",this.requestUpdate())}},100)}),this._resizeObserver.observe(this),this._intersectionObserver=new IntersectionObserver(e=>{this._visible=e[0].isIntersecting;const t=this.renderRoot.querySelector("svg");t&&(t.style.animationPlayState=this._visible?"running":"paused"),this._visible&&this._hass&&this._updateFlowsImperative()},{threshold:.01}),this._intersectionObserver.observe(this),this._onVisibility=()=>{"visible"===document.visibilityState&&this._hass&&(this._visible=!0,this._updateFlowsImperative())},document.addEventListener("visibilitychange",this._onVisibility)}disconnectedCallback(){super.disconnectedCallback(),this._resizeObserver&&(this._resizeObserver.disconnect(),this._resizeObserver=null),this._intersectionObserver&&(this._intersectionObserver.disconnect(),this._intersectionObserver=null),clearTimeout(this._updateTimer),clearTimeout(this._resizeTimeout),this._onVisibility&&(document.removeEventListener("visibilitychange",this._onVisibility),this._onVisibility=null);for(const e of Object.keys(this._animFrames))cancelAnimationFrame(this._animFrames[e]);this._animFrames={}}updated(){this._setupClickHandlers(),this._updateFlowsImperative()}static get styles(){return a`
            :host { display: block; }
            ha-card {
                overflow: hidden; padding: 0;
                background: var(--ha-card-background, var(--card-background-color, transparent)) !important;
                border-radius: var(--ha-card-border-radius, 12px);
            }
            svg { width: 100%; display: block; }
            .flow-group { transition: opacity 0.8s cubic-bezier(0.4,0,0.2,1); }
            .glow-ring { transition: opacity 1s ease; }
            #soc-arc, #autarky-arc { transition: stroke-dashoffset 1.5s cubic-bezier(0.4,0,0.2,1), stroke 1s ease; }
            text { font-variant-numeric: tabular-nums; }
            @keyframes socPulse { 0%,100%{opacity:1} 50%{opacity:0.6} }
            @keyframes socDrain { 0%,100%{opacity:0.75} 50%{opacity:0.4} }
            .clickable-node { cursor: pointer; pointer-events: bounding-box; }
            .clickable-node:hover { opacity: 0.85; }
            .device-clickable { cursor: pointer; }
            .device-clickable:hover { opacity: 0.85; }
        `}render(){if(!this._config)return q;const e=this._getLayout(),t=e.solar,i=e.inverter,s=e.battery,r=e.grid,a=e.home,o=e.ev,n=(2*Math.PI*e.socR).toFixed(1),l=(2*Math.PI*e.autarkyR).toFixed(1),c=e.font.label,d=e.font.value,p=e.font.sub,h=e.font.homeVal,_="'Segoe UI','Roboto',sans-serif",g=this._getNodeColor("grid_import"),u=this._getNodeColor("grid_export"),f=this._getNodeColor("solar"),m=this._getNodeColor("battery"),y=this._getNodeColor("home"),v=this._getNodeColor("ev"),x=wt.inverter.color,b=this._hasNode("solar"),$=this._hasNode("battery"),w=this._hasNode("grid"),k=this._hasNode("ev"),S=this._showInverter&&this._hasNode("inverter"),C=xe(this._hass,this._prefix);return W`
            <ha-card>
                <style>${be}</style>
                ${C.length>=2?W`
                    <div class="pv-strings-row">
                        ${C.map(e=>W`
                            <div class="pv-chip"
                                 title="${e.entityId}"
                                 data-entity="${e.entityId}"
                                 @click=${()=>this._fireMoreInfo?.(e.entityId)}>
                                <span class="pv-chip-label">${e.name}</span>
                                <span class="pv-chip-value">${(Math.abs(e.watts)/1e3).toFixed(2)} kW</span>
                            </div>
                        `)}
                    </div>
                `:q}
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="${e.vb}" style="background:transparent">
                    <defs>
                        <radialGradient id="bgGrad" cx="50%" cy="45%" r="60%">
                            <stop offset="0%" style="stop-color:var(--primary-text-color,#c8dcf0);stop-opacity:0.04"/>
                            <stop offset="100%" style="stop-color:transparent;stop-opacity:0"/>
                        </radialGradient>
                        <pattern id="dotGrid" width="50" height="50" patternUnits="userSpaceOnUse">
                            <circle cx="25" cy="25" r="0.7" fill="var(--secondary-text-color,#808080)" opacity="0.12"/>
                        </pattern>
                        ${this._svgRaw(this._glowFilter("glowSolar",f,8))}
                        ${this._svgRaw(this._glowFilter("glowBattery",m,8))}
                        ${this._svgRaw(this._glowFilter("glowGridImport",g,8))}
                        ${this._svgRaw(this._glowFilter("glowGridExport",u,8))}
                        ${this._svgRaw(this._glowFilter("glowHome",y,10))}
                        ${this._svgRaw(this._glowFilter("glowEV",v,8))}
                        ${this._svgRaw(this._glowFilter("glowInverter",x,6))}
                    </defs>

                    <rect width="100%" height="100%" fill="url(#bgGrad)"/>
                    <rect width="100%" height="90%"  fill="url(#dotGrid)"/>

                    ${this._svgRaw(b?this._track(e.paths.solar,f):"")}
                    ${this._svgRaw(b||S?this._track(e.paths.home,y):"")}
                    ${this._svgRaw($?this._track(e.paths.battery,m):"")}
                    ${this._svgRaw(w?`<path id="track-grid" d="${e.paths.grid}" fill="none" stroke="${g}" stroke-width="1.5" stroke-dasharray="4,6" opacity="0.18"/>`:"")}
                    ${this._svgRaw(k?this._track(e.paths.ev,v):"")}

                    ${this._svgRaw(b?`<g id="flow-solar" class="flow-group" style="opacity:0" data-path-d="${e.paths.solar}" data-color="${f}" data-count="2"></g>`:"")}
                    ${this._svgRaw($?`<g id="flow-battery" class="flow-group" style="opacity:0" data-path-d="${e.paths.battery}" data-color="${m}" data-count="3"></g>`:"")}
                    ${this._svgRaw(w?`<g id="flow-grid" class="flow-group" style="opacity:0" data-path-d="${e.paths.grid}" data-color="${g}" data-count="3"></g>`:"")}
                    ${this._svgRaw(b||S?`<g id="flow-home" class="flow-group" style="opacity:0" data-path-d="${e.paths.home}" data-color="${y}" data-count="2"></g>`:"")}
                    ${this._svgRaw(k?`<g id="flow-ev" class="flow-group" style="opacity:0" data-path-d="${e.paths.ev}" data-color="${v}" data-count="3"></g>`:"")}

                    ${this._svgRaw(b?`\n                    <g id="node-solar" filter="url(#glowSolar)">\n                        ${this._glowRing(t,f)}\n                        <circle cx="${t.cx}" cy="${t.cy}" r="${t.r}" fill="${this._hexToRgba(f,.07)}" stroke="${f}" stroke-width="1.8"/>\n                        <g transform="translate(${t.cx},${t.cy-8})" stroke="${f}" fill="none" opacity="0.75">\n                            <rect x="-16" y="-12" width="32" height="24" rx="3" stroke-width="1.8"/>\n                            <line x1="-16" y1="0" x2="16" y2="0" stroke-width="1.2"/>\n                            <line x1="-5" y1="-12" x2="-5" y2="12" stroke-width="1.2"/>\n                            <line x1="5" y1="-12" x2="5" y2="12" stroke-width="1.2"/>\n                            <line x1="0" y1="12" x2="0" y2="17" stroke-width="1.5"/>\n                            <line x1="-7" y1="17" x2="7" y2="17" stroke-width="1.5"/>\n                        </g>\n                    </g>\n                    <text x="${t.cx}" y="${t.cy+t.r+18}" text-anchor="middle" font-family="${_}" font-size="${c}" font-weight="600" fill="${f}">${this._escSvg(this._getNodeName("solar"))}</text>\n                    <text id="val-solar" x="${t.cx}" y="${t.cy+t.r+18+.9*d}" text-anchor="middle" font-family="${_}" font-size="${d}" font-weight="700" fill="${f}">0 W</text>\n                    <text id="val-today-solar" x="${t.cx}" y="${t.cy+t.r+18+.9*d+p+4}" text-anchor="middle" font-family="${_}" font-size="${p}" fill="${f}" opacity="0.7"> </text>\n                    `:"")}

                    ${this._svgRaw(S?`\n                    <g id="node-inverter" filter="url(#glowInverter)">\n                        <circle cx="${i.cx}" cy="${i.cy}" r="${i.r}" fill="${this._hexToRgba(x,.07)}" stroke="${x}" stroke-width="1"/>\n                        <path d="M${i.cx-10},${i.cy} Q${i.cx-4},${i.cy-8} ${i.cx},${i.cy} Q${i.cx+4},${i.cy+8} ${i.cx+10},${i.cy}" fill="none" stroke="${x}" stroke-width="1.8" opacity="0.7"/>\n                    </g>\n                    <text id="val-inverter-status" x="${i.cx}" y="${i.cy+i.r+14}" text-anchor="middle" font-family="${_}" font-size="${this._compact?11:10}" fill="var(--secondary-text-color,#5a7a9a)" opacity="0.7"> </text>\n                    `:"")}

                    ${this._svgRaw($?`\n                    <g id="node-battery" filter="url(#glowBattery)">\n                        ${this._glowRing(s,m)}\n                        <circle cx="${s.cx}" cy="${s.cy}" r="${s.r}" fill="${this._hexToRgba(m,.07)}" stroke="${m}" stroke-width="1.8"/>\n                        <circle cx="${s.cx}" cy="${s.cy}" r="${e.socR}" fill="none" stroke="${this._hexToRgba(m,.1)}" stroke-width="5"/>\n                        <circle id="soc-arc" cx="${s.cx}" cy="${s.cy}" r="${e.socR}" fill="none" stroke="${m}" stroke-width="5"\n                                stroke-dasharray="${n}" stroke-dashoffset="${n}"\n                                transform="rotate(-90 ${s.cx} ${s.cy})" stroke-linecap="round" opacity="0.75"/>\n                        <g transform="translate(${s.cx},${s.cy}) scale(0.8)" stroke="${m}" fill="none" opacity="0.7">\n                            <rect x="-8" y="-13" width="16" height="26" rx="3" stroke-width="1.8"/>\n                            <rect x="-3" y="-16" width="6" height="4" rx="1.5" fill="${m}" opacity="0.5" stroke="none"/>\n                        </g>\n                    </g>\n                    <text x="${s.cx}" y="${s.cy+s.r+18}" text-anchor="middle" font-family="${_}" font-size="${c}" font-weight="600" fill="${m}">${this._escSvg(this._getNodeName("battery"))}</text>\n                    <text id="val-battery-soc" x="${s.cx}" y="${s.cy+s.r+18+.9*d}" text-anchor="middle" font-family="${_}" font-size="${d}" font-weight="700" fill="${m}">0%</text>\n                    <text id="val-battery-power" x="${s.cx}" y="${s.cy+s.r+18+.9*d+c}" text-anchor="middle" font-family="${_}" font-size="${c}" font-weight="500" fill="${m}" opacity="0.7">0 W</text>\n                    <text id="label-battery-state" x="${s.cx}" y="${s.cy+s.r+18+.9*d+2*c}" text-anchor="middle" font-family="${_}" font-size="${p}" fill="${m}" opacity="0.7"></text>\n                    <text id="val-today-battery" x="${s.cx}" y="${s.cy+s.r+18+.9*d+2*c+p+4}" text-anchor="middle" font-family="${_}" font-size="${p}" fill="${m}" opacity="0.65"> </text>\n                    `:"")}

                    ${this._svgRaw(w?`\n                    <g id="node-grid" filter="url(#glowGridImport)">\n                        ${this._glowRing(r,g)}\n                        <circle id="grid-circle" cx="${r.cx}" cy="${r.cy}" r="${r.r}" fill="${this._hexToRgba(g,.07)}" stroke="${g}" stroke-width="1.8"/>\n                        <g id="grid-icon" transform="translate(${r.cx},${r.cy})" stroke="${g}" fill="none" opacity="0.7" stroke-width="1.8" stroke-linecap="round">\n                            <line x1="0" y1="-16" x2="0" y2="14"/>\n                            <line x1="-10" y1="-8" x2="10" y2="-8"/>\n                            <line x1="-7" y1="-1" x2="7" y2="-1"/>\n                            <line x1="-10" y1="-8" x2="-5" y2="14"/>\n                            <line x1="10" y1="-8" x2="5" y2="14"/>\n                        </g>\n                    </g>\n                    <text x="${r.cx}" y="${r.cy+r.r+18}" text-anchor="middle" font-family="${_}" font-size="${c}" font-weight="600" fill="${g}">${this._escSvg(this._getNodeName("grid"))}</text>\n                    <text id="val-grid" x="${r.cx}" y="${r.cy+r.r+18+.9*d}" text-anchor="middle" font-family="${_}" font-size="${d}" font-weight="700" fill="${g}">0 W</text>\n                    <text id="label-grid" x="${r.cx}" y="${r.cy+r.r+18+.9*d+c}" text-anchor="middle" font-family="${_}" font-size="${p}" font-weight="500" fill="${g}" opacity="0.7">GRID</text>\n                    <text id="val-today-grid" x="${r.cx}" y="${r.cy+r.r+18+.9*d+c+p+4}" text-anchor="middle" font-family="${_}" font-size="${p}" fill="${g}" opacity="0.65"> </text>\n                    `:"")}

                    <g id="node-home" filter="url(#glowHome)">
                        ${this._svgRaw(this._glowRing(a,y,1.4))}
                        <circle cx="${a.cx}" cy="${a.cy}" r="${a.r}" fill="${this._hexToRgba(y,.06)}" stroke="${y}" stroke-width="2"/>
                        <circle cx="${a.cx}" cy="${a.cy}" r="${e.autarkyR}" fill="none" stroke="${this._hexToRgba(y,.08)}" stroke-width="4"/>
                        <circle id="autarky-arc" cx="${a.cx}" cy="${a.cy}" r="${e.autarkyR}" fill="none" stroke="#4CAF50" stroke-width="4"
                                stroke-dasharray="${l}" stroke-dashoffset="${l}"
                                transform="rotate(-90 ${a.cx} ${a.cy})" stroke-linecap="round" opacity="0"/>
                        <g transform="translate(${a.cx},${a.cy-5})" stroke="${y}" fill="none" opacity="0.6" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M-20,2 L0,-14 L20,2"/>
                            <rect x="-14" y="2" width="28" height="20" rx="2"/>
                            <rect x="-4" y="10" width="8" height="12"/>
                        </g>
                    </g>
                    <text x="${a.cx}" y="${a.cy+a.r+18}" text-anchor="middle" font-family="${_}" font-size="${c+1}" font-weight="600" fill="${y}">${this._escSvg(this._getNodeName("home"))}</text>
                    <text id="val-home" x="${a.cx}" y="${a.cy+a.r+18+.9*h}" text-anchor="middle" font-family="${_}" font-size="${h}" font-weight="700" fill="${y}">0 W</text>
                    <text id="val-autarky" x="${a.cx}" y="${a.cy+a.r+18+.9*h+p+4}" text-anchor="middle" font-family="${_}" font-size="${p}" fill="${y}" opacity="0.7">\u00A0</text>
                    <text id="val-today-home" x="${a.cx}" y="${a.cy+a.r+18+.9*h+2*(p+4)}" text-anchor="middle" font-family="${_}" font-size="${p}" fill="${y}" opacity="0.65">\u00A0</text>

                    ${this._svgRaw(k?`\n                    <g id="node-ev" filter="url(#glowEV)">\n                        ${this._glowRing(o,v)}\n                        <circle cx="${o.cx}" cy="${o.cy}" r="${o.r}" fill="${this._hexToRgba(v,.07)}" stroke="${v}" stroke-width="1.8"/>\n                        <g transform="translate(${o.cx},${o.cy})" stroke="${v}" fill="none" opacity="0.7" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">\n                            <rect x="-8" y="-13" width="16" height="22" rx="3"/>\n                            <rect x="-5" y="-9" width="10" height="8" rx="1.5"/>\n                            <path d="M-1,-1 L0,3 L1,-1"/>\n                            <line x1="0" y1="9" x2="0" y2="13"/>\n                            <circle cx="0" cy="15" r="1.5" fill="${v}" opacity="0.4" stroke="none"/>\n                        </g>\n                    </g>\n                    <text x="${o.cx}" y="${o.cy+o.r+18}" text-anchor="middle" font-family="${_}" font-size="${c}" font-weight="600" fill="${v}">${this._escSvg(this._getNodeName("ev"))}</text>\n                    <text id="val-ev" x="${o.cx}" y="${o.cy+o.r+18+.9*d}" text-anchor="middle" font-family="${_}" font-size="${d}" font-weight="700" fill="${v}">0 W</text>\n                    <text id="val-today-ev" x="${o.cx}" y="${o.cy+o.r+18+.9*d+p+4}" text-anchor="middle" font-family="${_}" font-size="${p}" fill="${v}" opacity="0.65"> </text>\n                    <text id="val-ev-subtitle" x="${o.cx}" y="${o.cy+o.r+18+.9*d+2*(p+4)}" text-anchor="middle" font-family="${_}" font-size="${p-1}" fill="${v}" opacity="0.6"></text>\n                    `:"")}

                    <g id="device-labels"></g>

                    <text x="${this._compact?470:960}" y="${this._compact?1050:770}" text-anchor="end"
                          font-family="${_}" font-size="10" font-weight="300" letter-spacing="2"
                          fill="var(--secondary-text-color,#808080)" opacity="0.15">SEM</text>
                </svg>
            </ha-card>
        `}_svgRaw(e){return e?$t(e):q}_escSvg(e){return e?String(e).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;"):""}_updateFlowsImperative(){if(!this._hass)return;let e,t,i,s=this._getState("solar_power");if(this._entities?.solar?.reverse&&(s=-s),"entities"===this._mode&&(this._entities?.battery?.charge||this._entities?.battery?.discharge))e=this._getState("battery_charge_power")-this._getState("battery_discharge_power");else{let t=this._getState("battery_power");e=this._entities?.battery?.reverse?-t:t}if("entities"===this._mode&&this._entities?.grid?.entity){const e=this._getState("grid_power"),s=this._entities.grid.reverse;t=Math.max(0,s?-e:e),i=Math.max(0,s?e:-e)}else t=this._getState("grid_import_power"),i=this._getState("grid_export_power");let r=this._getState("ev_power");this._entities?.ev?.invert&&(r=-r);const a=this._getState("battery_soc"),o=this._getState("autarky_rate"),n=Math.max(0,e),l=Math.max(0,-e),c=this._getEntityId("home_consumption_power");let d;c&&this._hass?.states[c]?(d=this._getState("home_consumption_power"),this._entities?.home?.invert&&(d=-d)):d=Math.max(0,s+t+l-i-n-r);const p=this._getStateStr("daily_solar_energy"),h=this._getStateStr("daily_ev_energy"),_=this._getStateStr("daily_grid_import_energy"),g=this._getStateStr("daily_grid_export_energy"),u=this._getStateStr("daily_battery_energy"),f=this._getStateStr("daily_home_energy"),m={solar:s,battery:e,gridImport:t,gridExport:i,home:d,ev:r,soc:a,autarky:o,dailySolar:p,dailyEv:h,dailyGridImport:_,dailyGridExport:g,dailyBattery:u,dailyHome:f},y=JSON.stringify(m);if(this._lastKey===y)return;this._lastKey=y,this._animateValue("val-solar",s);const v=e>10?"▼ ":e<-10?"▲ ":"";this._animateValue("val-battery-power",Math.abs(e),800,e=>v+ge(e));const x=t>i,b=x?"↓ ":i>10?"↑ ":"";this._animateValue("val-grid",x?t:i,800,e=>b+ge(e)),this._animateValue("val-home",d),this._animateValue("val-ev",r);const $=this._getState("ev_charger_count");this._setText("val-ev-subtitle",$>1?`(${$} ${this._t("chargers")})`:""),this._animateValue("val-battery-soc",a,800,e=>`${e.toFixed(0)}%`);const w=this._getEntityId("autarky_rate");w&&this._animateValue("val-autarky",o,800,e=>`⚡ ${e.toFixed(0)}% self`),this._setText("val-inverter-status",this._getStateStr("charging_state"));const k=this._t("today");this._setText("val-today-solar",p?`${k} ${p} kWh`:""),this._setText("val-today-ev",h?`${k} ${h} kWh`:""),this._setText("val-today-battery",u?`${k} ${u} kWh`:""),this._setText("val-today-home",f?`${k} ${f} kWh`:"");const S=[];if(_&&S.push(`↓${_}`),g&&S.push(`↑${g}`),_&&g){const e=(parseFloat(_)-parseFloat(g)).toFixed(1);S.push(`Net ${e>0?"+":""}${e}`)}this._setText("val-today-grid",S.length?S.join(" ")+" kWh":"");const C=this._getLayout(),z=this.renderRoot.getElementById("soc-arc");if(z){const e=2*Math.PI*C.socR;z.style.strokeDashoffset=(e*(1-a/100)).toFixed(1),z.style.animation=n>10?"socPulse 2s ease-in-out infinite":l>10?"socDrain 2.5s ease-in-out infinite":"none"}const M=this.renderRoot.getElementById("autarky-arc");if(M&&w&&o>0){const e=2*Math.PI*C.autarkyR;M.style.strokeDashoffset=(e*(1-o/100)).toFixed(1),M.style.stroke=this._autarkyColor(o),M.style.opacity="0.75"}else M&&(M.style.opacity="0");const E=x?this._getNodeColor("grid_import"):i>10?this._getNodeColor("grid_export"):this._getNodeColor("grid_import");this._updateGridColor(E,x);const D=this.renderRoot.getElementById("label-grid");D&&(D.textContent=x?this._t("importing"):i>10?this._t("exporting"):this._t("grid"));const F=n>10?"#f06292":l>10?"#4db6ac":this._getNodeColor("battery"),I=this.renderRoot.getElementById("label-battery-state");I&&(I.textContent=n>10?this._t("charging"):l>10?this._t("discharging"):"");for(const e of["val-battery-soc","val-battery-power","label-battery-state","val-today-battery"]){const t=this.renderRoot.getElementById(e);t&&t.setAttribute("fill",F)}const B=this.renderRoot.getElementById("soc-arc");B&&(n>10||l>10)&&(B.style.stroke=F),this._updateFlow("flow-solar",s>10,!1,fe(s)),this._updateFlow("flow-battery",Math.abs(e)>10,e<0,fe(e),F),this._updateFlow("flow-grid",t>10||i>10,x,fe(t||i),E),this._updateFlow("flow-home",d>10,!1,fe(d)),this._updateFlow("flow-ev",r>10,!1,fe(r)),this._setGlowIntensity("node-solar",s,1e4),this._setGlowIntensity("node-battery",Math.abs(e),5e3),this._setGlowIntensity("node-grid",Math.max(t,i),1e4),this._setGlowIntensity("node-home",d,8e3),this._setGlowIntensity("node-ev",r,11e3),this._updateDeviceLabels()}_updateFlow(e,t,i,s,r){const a=this.renderRoot.getElementById(e);if(!a)return;if(a.style.opacity=t?"1":"0",!t)return void(a.dataset.sig="");const o=r||a.dataset.color;r&&(a.dataset.color=r);const n=a.dataset.pathD,l=parseInt(a.dataset.count,10)||2,c=`${i?"r":"f"}:${s.toFixed(1)}:${o}`;a.dataset.sig!==c&&(a.dataset.sig=c,a.innerHTML=this._flowEffects(n,o,l,s,i))}_flowEffects(e,t,i,s,r){const a=s.toFixed(1),o=r?' keyPoints="1;0" keyTimes="0;1"':"";let n=`<path d="${e}" fill="none" stroke="${t}" stroke-width="3"\n                     stroke-dasharray="12,20" opacity="0.5" stroke-linecap="round">\n                     <animate attributeName="stroke-dashoffset" from="0" to="${r?"32":"-32"}"\n                              dur="${a}s" repeatCount="indefinite"/>\n                   </path>`;for(let r=0;r<i;r++){const l=r/i*s;n+=`\n                <circle r="5" fill="${t}" opacity="0.12">\n                    <animateMotion path="${e}" dur="${a}s" repeatCount="indefinite" calcMode="paced"${o} begin="-${l.toFixed(2)}s"/>\n                </circle>\n                <circle r="2.5" fill="${t}" opacity="0.9">\n                    <animateMotion path="${e}" dur="${a}s" repeatCount="indefinite" calcMode="paced"${o} begin="-${l.toFixed(2)}s"/>\n                </circle>`}return n}_updateGridColor(e,t){const i=this.renderRoot.getElementById("node-grid");i&&i.setAttribute("filter",`url(#glowGrid${t?"Import":"Export"})`);const s=this.renderRoot.getElementById("grid-circle");s&&(s.setAttribute("stroke",e),s.setAttribute("fill",this._hexToRgba(e,.07)));const r=this.renderRoot.querySelector("#node-grid .glow-ring");r&&r.setAttribute("stroke",e);const a=this.renderRoot.getElementById("grid-icon");a&&a.setAttribute("stroke",e);for(const t of["val-grid","label-grid","val-today-grid"]){const i=this.renderRoot.getElementById(t);i&&i.setAttribute("fill",e)}const o=this.renderRoot.getElementById("track-grid");o&&o.setAttribute("stroke",e)}_updateDeviceLabels(){const e=this.renderRoot.getElementById("device-labels");if(!e)return;const t=this._getDeviceList(),i=t.map(([e,t],i)=>`${t.power_entity}:${t.name}:${t.color||he[i%he.length]}:${t.icon_override||""}:${t.daily_energy_entity||""}`).join("|");this._deviceConfigSig!==i&&(this._deviceConfigSig=i,this._buildDeviceDOM(e,t)),this._updateDeviceValues(t)}_getDeviceList(){let e=[];if("entities"===this._mode&&this._entities?.individual)e=this._entities.individual.map((e,t)=>[e.entity||`device_${t}`,{name:e.name||e.entity?.split(".").pop()||`Device ${t+1}`,power_entity:e.entity,device_type:e.device_type||"appliance",is_on:!1,current_power:0,color:e.color,icon_override:e.icon,daily_energy_entity:e.daily_energy}]);else if("prefix"===this._mode){const t=this._hass.states[`${this._prefix}controllable_devices_count`];t?.attributes?.devices&&(e=Object.entries(t.attributes.devices).filter(([,e])=>e.power_entity||e.current_power>0).sort((e,t)=>(e[1].priority||5)-(t[1].priority||5)))}return e.slice(0,6)}_buildDeviceDOM(e,t){if(!t.length)return e.innerHTML="",void(this._devicePositions=[]);const i="'Segoe UI','Roboto',sans-serif",s=this._getLayout(),r=s.home,a=this._compact,o=a?26:24,n=a?2:Math.min(t.length,3),l=a?30:60,c=((a?500:1e3)-2*l)/n,d=s.deviceY,p=a?18:20;let h="";this._devicePositions=[],t.forEach(([e,t],s)=>{let _=t.name||e;_.length>p&&(_=_.substring(0,p-1)+"…");const g=t.color||he[s%he.length],u=this._deviceIcon(t.device_type,t.name||e),f=s%n,m=Math.floor(s/n),y=l+f*c+c/2,v=d+m*(a?100:90);this._devicePositions.push({cx:y,cy:v,nodeR:o,color:g}),h+=`<path id="dev-conn-${s}" d="M${r.cx},${r.cy+r.r} C${r.cx},${r.cy+r.r+30} ${y},${v-40} ${y},${v-o}" fill="none" stroke="${g}" stroke-width="1.2" stroke-dasharray="3,5" opacity="0.1"/>`,h+=`<g id="dev-flow-${s}"></g>`;const x=t.power_entity?` data-entity="${t.power_entity}"`:"";h+=`<g id="dev-group-${s}" class="device-clickable"${x} data-idx="${s}">`,h+=`<circle id="dev-circle-${s}" cx="${y}" cy="${v}" r="${o}" fill="rgba(128,128,128,0.03)" stroke="${g}" stroke-width="1.2" opacity="0.4"/>`,h+=`<g transform="translate(${y},${v})" stroke="${g}" fill="none" opacity="0.35" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">${u}</g>`,h+=`<text x="${y}" y="${v+o+14}" text-anchor="middle" font-family="${i}" font-size="11" font-weight="500" fill="${g}" opacity="0.8">${this._escSvg(_)}</text>`,h+=`<text id="dev-val-${s}" x="${y}" y="${v+o+14+11+2}" text-anchor="middle" font-family="${i}" font-size="11" font-weight="600" fill="${g}" opacity="0.7">0 W</text>`,h+=`<text id="dev-daily-${s}" x="${y}" y="${v+o+14+26}" text-anchor="middle" font-family="${i}" font-size="11" fill="${g}" opacity="0.65"></text>`,h+="</g>"}),e.innerHTML=h,e.querySelectorAll(".device-clickable[data-entity]").forEach(e=>{const t=parseInt(e.dataset.idx);this._setupNodeActions(e,`device_${t}`,e.dataset.entity)}),t.forEach((e,t)=>{delete this._currentValues[`dev-val-${t}`]})}_updateDeviceValues(e){const t=this._getLayout().home;e.forEach(([e,i],s)=>{const r=i.power_entity?this._hass.states[i.power_entity]:null,a=r?parseFloat(r.state)||0:i.current_power||0,o=a>5,n=i.color||he[s%he.length],l=this._devicePositions[s];if(!l)return;if(this._animateValue(`dev-val-${s}`,a),i.daily_energy_entity){const e=this._hass.states[i.daily_energy_entity];this._setText(`dev-daily-${s}`,e?`${this._t("today")} ${e.state} kWh`:"")}const c=this.renderRoot.getElementById(`dev-conn-${s}`);c&&c.setAttribute("opacity",o?"0.3":"0.1");const d=this.renderRoot.getElementById(`dev-circle-${s}`);d&&(d.setAttribute("fill",`rgba(128,128,128,${o?.08:.03})`),d.setAttribute("opacity",o?"1":"0.4"));const p=this.renderRoot.getElementById(`dev-val-${s}`);p&&p.setAttribute("opacity",o?"1":"0.5");const h=this.renderRoot.getElementById(`dev-group-${s}`);if(h){const e=h.querySelector("g[transform]");e&&e.setAttribute("opacity",o?"0.7":"0.35")}const _=this.renderRoot.getElementById(`dev-flow-${s}`);if(_)if(a>5){const e=fe(a).toFixed(1);if(_.dataset.sig!==e){_.dataset.sig=e;const i=`M${t.cx},${t.cy+t.r} C${t.cx},${t.cy+t.r+30} ${l.cx},${l.cy-40} ${l.cx},${l.cy-l.nodeR}`;_.innerHTML=`\n                            <path d="${i}" fill="none" stroke="${n}" stroke-width="2" stroke-dasharray="8,16" opacity="0.4" stroke-linecap="round">\n                                <animate attributeName="stroke-dashoffset" from="0" to="-24" dur="${e}s" repeatCount="indefinite"/>\n                            </path>\n                            <circle r="2" fill="${n}" opacity="0.8">\n                                <animateMotion path="${i}" dur="${e}s" repeatCount="indefinite" calcMode="paced" begin="-${(.3*s).toFixed(1)}s"/>\n                            </circle>`}}else""!==_.dataset.sig&&(_.dataset.sig="",_.innerHTML="")})}_setupClickHandlers(){const e={"node-solar":"solar_power","val-solar":"solar_power","val-today-solar":"daily_solar_energy","node-battery":"battery_soc","val-battery-soc":"battery_soc","val-battery-power":"battery_power","label-battery-state":"battery_power","val-today-battery":"daily_battery_energy","node-grid":"grid_import_power","val-grid":"grid_import_power","label-grid":"grid_import_power","val-today-grid":"daily_grid_import_energy","node-home":"home_consumption_power","val-home":"home_consumption_power","val-autarky":"autarky_rate","val-today-home":"daily_home_energy","node-ev":"ev_power","val-ev":"ev_power","val-today-ev":"daily_ev_energy","val-inverter-status":"charging_state"};for(const[t,i]of Object.entries(e)){const e=this._getEntityId(i);if(!e)continue;const s=this.renderRoot.getElementById(t);s&&(s.setAttribute("data-entity",e),s.style.cursor="pointer")}const t=this.renderRoot.querySelector("svg");t&&!t._semClickBound&&(t._semClickBound=!0,t.addEventListener("click",e=>{let i=e.target;for(let e=0;e<5&&i&&i!==t;e++){const e=i.getAttribute?.("data-entity");if(e)return void this._fireMoreInfo(e);i=i.parentElement}}));const i=[{ids:["node-solar"],node:"solar",key:"solar_power"},{ids:["node-battery"],node:"battery",key:"battery_soc"},{ids:["node-grid"],node:"grid",key:"grid_import_power"},{ids:["node-home"],node:"home",key:"home_consumption_power"},{ids:["node-ev"],node:"ev",key:"ev_power"}];for(const{ids:e,node:t,key:s}of i){const i=this._getEntityId(s);if(i)for(const s of e){const e=this.renderRoot.getElementById(s);e&&!e._semActionsBound&&(e._semActionsBound=!0,e.classList.add("clickable-node"),this._setupNodeActions(e,t,i))}}}_setupNodeActions(e,t,i){let s=null,r=!1,a=0,o=null;e.style.cursor="pointer",e.addEventListener("pointerdown",()=>{r=!1,s=setTimeout(()=>{r=!0;const e=this._getActionConfig(t,"hold_action");"none"!==e.action&&this._handleAction(e,i)},500)}),e.addEventListener("pointerup",()=>clearTimeout(s)),e.addEventListener("pointercancel",()=>{clearTimeout(s),r=!1}),e.addEventListener("click",()=>{if(r)return void(r=!1);const e=this._getActionConfig(t,"double_tap_action");if(!e||"none"===e.action)return void this._handleAction(this._getActionConfig(t,"tap_action"),i);const s=Date.now();s-a<300?(clearTimeout(o),a=0,this._handleAction(e,i)):(a=s,o=setTimeout(()=>{a=0,this._handleAction(this._getActionConfig(t,"tap_action"),i)},300))})}_getActionConfig(e,t){const i=this._entities;if(!i)return{action:"tap_action"===t?"more-info":"none"};let s;if(e.startsWith("device_")){const t=parseInt(e.split("_")[1]);s=i.individual?.[t]}else{s={solar:i.solar,battery:i.battery,grid:i.grid,home:i.home,ev:i.ev||i.individual?.[0]}[e]}const r=s?.[t];return r?"string"==typeof r?{action:r}:r:{action:"tap_action"===t?"more-info":"none"}}_handleAction(e,t){switch(e||(e={action:"more-info"}),e.action){case"more-info":this._fireMoreInfo(e.entity||t);break;case"toggle":this._hass&&this._hass.callService("homeassistant","toggle",{entity_id:e.entity||t});break;case"navigate":e.navigation_path&&(window.history.pushState(null,"",e.navigation_path),window.dispatchEvent(new CustomEvent("location-changed")));break;case"call-service":if(e.service&&this._hass){const[t,i]=e.service.split(".");this._hass.callService(t,i,e.service_data||{})}break;case"url":e.url_path&&window.open(e.url_path,"_blank")}}_fireMoreInfo(e){e&&this.dispatchEvent(new CustomEvent("hass-more-info",{detail:{entityId:e},bubbles:!0,composed:!0}))}_setGlowIntensity(e,t,i){const s=this.renderRoot.querySelector(`#${e} .glow-ring`);if(!s)return;const r=Math.min(1,Math.abs(t)/i);s.style.opacity=(.15+.85*r).toFixed(2)}_animateValue(e,t,i=800,s=null){const r=this.renderRoot.getElementById(e);if(!r)return;this._animFrames[e]&&cancelAnimationFrame(this._animFrames[e]);const a=s||(e=>ge(e)),o=this._currentValues[e]||0;if(this._currentValues[e]=t,Math.abs(o-t)<.5)return void(r.textContent=a(t));const n=performance.now(),l=s=>{const c=Math.min(1,(s-n)/i),d=c<.5?2*c*c:1-Math.pow(-2*c+2,2)/2;r.textContent=a(o+(t-o)*d),c<1?this._animFrames[e]=requestAnimationFrame(l):delete this._animFrames[e]};this._animFrames[e]=requestAnimationFrame(l),setTimeout(()=>{this._currentValues[e]===t&&(this._animFrames[e]&&(cancelAnimationFrame(this._animFrames[e]),delete this._animFrames[e]),r.textContent=a(t))},i+250)}_setText(e,t){const i=this.renderRoot.getElementById(e);i&&(i.textContent=t)}_getState(e){if(!this._hass)return 0;const t="prefix"===this._mode?`${this._prefix}${e}`:this._resolveEntity(e);if(!t)return 0;const i=this._hass.states[t];if(!i)return 0;const s=parseFloat(i.state);return isNaN(s)?0:s}_getStateStr(e){if(!this._hass)return"";const t="prefix"===this._mode?`${this._prefix}${e}`:this._resolveEntity(e);if(!t)return"";const i=this._hass.states[t];return i?i.state:""}_getEntityId(e){return"prefix"===this._mode?`${this._prefix}${e}`:this._resolveEntity(e)}_resolveEntity(e){const t=this._entities;if(!t)return null;return{solar_power:t.solar?.entity,battery_power:t.battery?.entity,battery_charge_power:t.battery?.charge,battery_discharge_power:t.battery?.discharge,grid_power:t.grid?.entity,grid_import_power:t.grid?.consumption,grid_export_power:t.grid?.production,ev_power:t.ev?.entity||t.individual?.[0]?.entity,battery_soc:t.battery?.state_of_charge,home_consumption_power:t.home?.entity,charging_state:t.inverter?.entity,daily_solar_energy:t.solar?.daily_energy,daily_ev_energy:t.ev?.daily_energy||t.individual?.[0]?.daily_energy,daily_grid_import_energy:t.grid?.daily_import_energy,daily_grid_export_energy:t.grid?.daily_export_energy,daily_battery_energy:t.battery?.daily_energy,daily_home_energy:t.home?.daily_energy,autarky_rate:t.home?.autarky,ev_charger_count:t.ev?.charger_count||"sensor.sem_ev_charger_count"}[e]||null}_hasNode(e){if("ev"===e&&!this._showEv)return!1;if("battery"===e&&!this._showBattery)return!1;if("prefix"===this._mode)return!0;const t=this._entities;if(!t)return!1;return{solar:!!t.solar?.entity,battery:!!(t.battery?.entity||t.battery?.charge||t.battery?.discharge),grid:!(!t.grid?.consumption&&!t.grid?.entity),home:!0,ev:!(!t.ev?.entity&&!t.individual?.[0]?.entity),inverter:!!t.inverter?.entity||!!t.solar?.entity}[e]||!1}_getNodeColor(e){const t=this._entities,i={solar:wt.solar.color,battery:wt.battery.color,grid:wt.grid.color_import,grid_import:wt.grid.color_import,grid_export:wt.grid.color_export,home:wt.home.color,ev:wt.ev.color,inverter:wt.inverter.color};if(!t)return i[e]||"#888";return{solar:t.solar?.color,battery:t.battery?.color,grid:t.grid?.color_import,grid_import:t.grid?.color_import,grid_export:t.grid?.color_export,home:t.home?.color,ev:t.ev?.color||t.individual?.[0]?.color}[e]||i[e]||"#888"}_getNodeName(e){const t=this._entities,i=wt[e]?.nameKey,s=i?this._t(i):e;if(!t)return s;return{solar:t.solar?.name,battery:t.battery?.name,grid:t.grid?.name,home:t.home?.name,ev:t.ev?.name||t.individual?.[0]?.name}[e]||s}_getLayout(){return this._compact?{vb:"0 0 500 1100",solar:{cx:250,cy:70,r:48},inverter:{cx:250,cy:225,r:20},battery:{cx:100,cy:340,r:48},grid:{cx:400,cy:340,r:48},home:{cx:250,cy:510,r:60},ev:{cx:100,cy:660,r:42},socR:33,autarkyR:48,paths:{solar:"M250,118 L250,205",home:"M250,245 L250,450",battery:"M230,230 C180,260 120,290 100,292",grid:"M270,230 C320,260 380,290 400,292",ev:"M230,240 C180,380 130,560 100,618"},font:{label:14,value:22,sub:12,homeVal:26},deviceY:810}:{vb:"0 0 1000 800",solar:{cx:500,cy:65,r:50},inverter:{cx:500,cy:210,r:20},battery:{cx:150,cy:270,r:50},grid:{cx:850,cy:270,r:50},home:{cx:500,cy:385,r:62},ev:{cx:150,cy:460,r:44},socR:40,autarkyR:50,paths:{solar:"M500,115 L500,190",home:"M500,230 L500,323",battery:"M480,215 C380,230 250,245 200,270",grid:"M520,215 C620,230 750,245 800,270",ev:"M480,225 C380,330 250,410 195,460"},font:{label:13,value:20,sub:11,homeVal:24},deviceY:590}}_glowFilter(e,t,i){return`<filter id="${e}" x="-30%" y="-30%" width="160%" height="160%">\n            <feGaussianBlur stdDeviation="${i}" result="blur"/>\n            <feFlood flood-color="${t}" flood-opacity="0.25"/>\n            <feComposite in2="blur" operator="in"/>\n            <feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge>\n        </filter>`}_glowRing(e,t,i=1.2){const s=e.r+5;return`<circle class="glow-ring" cx="${e.cx}" cy="${e.cy}" r="${s}" fill="none" stroke="${t}" stroke-width="${i}" opacity="0.3">\n            <animate attributeName="r" values="${s};${s+5};${s}" dur="3s" repeatCount="indefinite"/>\n            <animate attributeName="opacity" values="0.3;0.12;0.3" dur="3s" repeatCount="indefinite"/>\n        </circle>`}_track(e,t){return`<path d="${e}" fill="none" stroke="${t}" stroke-width="1.5" stroke-dasharray="4,6" opacity="0.18"/>`}_hexToRgba(e,t){const i=e.match(/^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i);return i?`rgba(${parseInt(i[1],16)},${parseInt(i[2],16)},${parseInt(i[3],16)},${t})`:`rgba(128,128,128,${t})`}_autarkyColor(e){if((e=Math.max(0,Math.min(100,e)))<=50){const t=e/50;return`rgb(220,${Math.round(50+150*t)},50)`}const t=(e-50)/50;return`rgb(${Math.round(220-170*t)},200,50)`}_deviceIcon(e,t){const i=(t||"").toLowerCase();return"ev_charger"===(e||"").toLowerCase()||i.includes("keba")||i.includes("charger")||i.includes("wallbox")?'<rect x="-6" y="-10" width="12" height="16" rx="2"/><path d="M-2,-4 L0,2 L2,-4"/><line x1="0" y1="6" x2="0" y2="10"/>':i.includes("heiz")||i.includes("heat")||i.includes("warm")||i.includes("boiler")?'<path d="M-4,-10 C-4,-4 4,-4 4,-10"/><path d="M-4,-3 C-4,3 4,3 4,-3"/><path d="M-4,4 C-4,10 4,10 4,4"/>':i.includes("wash")||i.includes("spül")||i.includes("geschirr")||i.includes("wasch")?'<circle r="10" fill="none"/><circle r="5" fill="none"/><circle r="1.5" fill="currentColor" opacity="0.3" stroke="none"/>':i.includes("dryer")||i.includes("trockn")?'<circle r="10" fill="none"/><path d="M-4,-4 C0,-8 0,8 4,4" fill="none"/>':i.includes("pool")||i.includes("pump")?'<circle r="8" fill="none"/><path d="M-6,0 L6,0 M0,-6 L0,6" opacity="0.5"/><path d="M-4,-4 L4,4 M4,-4 L-4,4"/>':i.includes("klima")||i.includes("ac")||i.includes("cool")||i.includes("air")?'<rect x="-10" y="-6" width="20" height="12" rx="2"/><path d="M-6,6 C-6,10 -2,10 -2,6" fill="none"/><path d="M2,6 C2,10 6,10 6,6" fill="none"/>':i.includes("light")||i.includes("licht")||i.includes("lamp")?'<path d="M-5,-10 C-8,-2 -3,4 -2,6 L2,6 C3,4 8,-2 5,-10 C2,-14 -2,-14 -5,-10Z" fill="none"/><line x1="-2" y1="8" x2="2" y2="8"/>':i.includes("shelly")||i.includes("plug")||i.includes("switch")||i.includes("steckdose")?'<rect x="-8" y="-10" width="16" height="20" rx="3"/><circle cx="-3" cy="-2" r="2" fill="none"/><circle cx="3" cy="-2" r="2" fill="none"/><line x1="0" y1="4" x2="0" y2="7"/>':'<path d="M-3,-10 L-3,0 L-6,0 L0,10 L0,0 L3,0 L-3,-10Z" fill="none"/>'}getCardSize(){return 8}static async getConfigElement(){return document.createElement("sem-flow-card-editor")}static getStubConfig(e){const t=e?Object.keys(e.states):[],i=e=>{for(const i of e){const e=t.find(e=>e.includes(i));if(e)return e}return null};return{entities:{solar:{entity:i(["solar_power","pv_power"])||"sensor.solar_power"},grid:{consumption:i(["grid_import","grid_consumption"])||"sensor.grid_import_power",production:i(["grid_export","grid_feed"])||"sensor.grid_export_power"},battery:{entity:i(["battery_power","batt_power"])||"sensor.battery_power",state_of_charge:i(["battery_soc","battery_level"])||"sensor.battery_soc"},home:{entity:i(["home_consumption","house_power"])||"sensor.home_consumption_power"}}}}},{type:"sem-flow-card",name:"SEM Flow Card",description:"Animated energy flow diagram — works with any HA entities"});const kt="sensor.sem_",St=["solar_power","battery_power","grid_import_power","grid_export_power","ev_power","battery_soc","battery_temperature","charging_state","home_consumption_power","daily_solar_energy","daily_battery_charge_energy","daily_battery_discharge_energy","daily_ev_energy","daily_home_energy","daily_grid_import_energy","daily_grid_export_energy","forecast_today_kwh","controllable_devices_count"];$e("sem-system-diagram-card",class extends ke{static properties={_solarDisp:{state:!0},_battDisp:{state:!0},_homeDisp:{state:!0},_evDisp:{state:!0},_gridDisp:{state:!0},_gridDispMode:{state:!0},_sunTransform:{state:!0},_moonTransform:{state:!0},_sunPowerX:{state:!0},_sunPowerY:{state:!0},_sunPtX:{state:!0},_sunPtY:{state:!0}};static get watchedEntities(){return St.map(e=>`${kt}${e}`)}constructor(){super(),this._prefix=kt,this._mode="prefix",this._entities=null,this._compact=!1,this._visible=!0,this._resizeObserver=null,this._intersectionObserver=null,this._resizeTimeout=null,this._counterRaf=null,this._targets=null,this._lastDiagKey="",this._sunSparkProps=null,this._sunSparkSig="",this._sparkWaveD=""}setConfig(e){super.setConfig(e),e.entities&&!e.entity_prefix?(this._mode="entities",this._entities=e.entities):(this._mode="prefix",this._entities=null),this._prefix=e.entity_prefix||kt,this._showEv=!1!==e.show_ev,this._showBattery=!1!==e.show_battery}_eid(e){if("entities"!==this._mode)return`${this._prefix}${e}`;const t=this._entities;if(!t)return null;return{solar_power:t.solar?.entity,battery_power:t.battery?.entity,battery_charge_power:t.battery?.charge,battery_discharge_power:t.battery?.discharge,grid_power:t.grid?.entity,grid_import_power:t.grid?.consumption,grid_export_power:t.grid?.production,ev_power:t.ev?.entity||t.individual?.[0]?.entity,battery_soc:t.battery?.state_of_charge,battery_temperature:t.battery?.temperature,home_consumption_power:t.home?.entity,charging_state:t.inverter?.entity,daily_solar_energy:t.solar?.daily_energy,daily_ev_energy:t.ev?.daily_energy||t.individual?.[0]?.daily_energy,daily_grid_import_energy:t.grid?.daily_import_energy,daily_grid_export_energy:t.grid?.daily_export_energy,daily_battery_charge_energy:t.battery?.daily_charge_energy,daily_battery_discharge_energy:t.battery?.daily_discharge_energy,daily_home_energy:t.home?.daily_energy,autarky_rate:t.home?.autarky,self_consumption_rate:t.home?.self_consumption,forecast_today_kwh:t.solar?.forecast_remaining,controllable_devices_count:t.devices?.count_entity}[e]||null}_flowSolar(){const e=this._val("solar_power");return this._entities?.solar?.reverse?-e:e}_flowBattery(){const e=this._entities;if(e?.battery?.charge||e?.battery?.discharge)return this._val("battery_charge_power")-this._val("battery_discharge_power");const t=this._val("battery_power");return e?.battery?.reverse?-t:t}_flowGridPair(){const e=this._entities;if("entities"===this._mode&&e?.grid?.entity){const t=this._state(e.grid.entity,0),i=e.grid.reverse;return{gridImport:Math.max(0,i?-t:t),gridExport:Math.max(0,i?t:-t)}}return{gridImport:this._val("grid_import_power"),gridExport:this._val("grid_export_power")}}_flowEv(){const e=this._val("ev_power");return this._entities?.ev?.invert?-e:e}_flowHome(e,t,i,s,r,a){const o=this._eid("home_consumption_power"),n=o?this._hass?.states[o]:null;if(n&&"unavailable"!==n.state&&"unknown"!==n.state){let e=this._state(o,0);return this._entities?.home?.invert&&(e=-e),Math.max(0,e)}return Math.max(0,e+t+r-i-s-a)}set hass(e){this._hass=e;const t=e?.language,i="function"==typeof semLocalize;let s=!1;if((t!==this._lang||i&&!this._localizeReady)&&(this._lang=t,this._localizeReady=i,s=!0),this._isFrozen()&&!s)return;const r=this._eid("solar_power"),a=r?e?.states[r]?.state:void 0;if(("unavailable"===a||"unknown"===a)&&!s)return;const o=St.filter(e=>!(!this._showEv&&"ev_power"===e)&&!!(this._showBattery||"battery_power"!==e&&"battery_soc"!==e&&"battery_temperature"!==e));let n=o.map(t=>{const i=this._eid(t);return i&&e?.states[i]?.state||""}).join(",")+"|"+t;n+="|"+ve(e,this._prefix),this._showEv&&(n+="|"+(e?.states["binary_sensor.sem_ev_connected"]?.state||""),n+="|"+(e?.states["binary_sensor.sem_ev_charging"]?.state||""));const l=e?.states["sun.sun"];if(n+="|"+(l?.attributes?.elevation??"")+":"+(l?.attributes?.next_rising||"")+":"+(l?.attributes?.next_setting||""),n===this._lastDiagKey&&!s)return;this._lastDiagKey=n;const c=this._flowSolar(),d=this._flowBattery(),p=Math.max(0,d),h=Math.max(0,-d),{gridImport:_,gridExport:g}=this._flowGridPair(),u=this._flowEv(),f=this._flowHome(c,_,g,p,h,u);this._targets={solar:c,batt:Math.abs(d),home:f,ev:u,grid:g>10?g:_>10?_:0,gridMode:g>10?"↑":_>10?"↓":null},this._startTickIfIdle(),this._scheduleUpdate()}get hass(){return this._hass}_val(e,t=0){const i=this._eid(e);return i?this._state(i,t):t}_valStr(e){const t=this._eid(e);return t?this._stateStr(t):""}_readWithHold(e,t,i){const s=this._eid(e),r=s?this._hass?.states[s]:void 0,a=r?.state,o=r&&"unavailable"!==a&&"unknown"!==a,n=Date.now(),l=t+"Ts",c=t.startsWith("this.")?t.slice(5):t,d=l.startsWith("this.")?l.slice(5):l;if(o){const e=parseFloat(a);if(!Number.isNaN(e))return this[c]=e,this[d]=n,{value:e,stale:!1}}return null!=this[c]&&n-(this[d]||0)<i?{value:this[c],stale:!1}:{value:0,stale:!0}}_startTickIfIdle(){if(this._counterRaf)return;const e=(e,t)=>{const i=e??0,s=t-i;return Math.abs(s)<.5?t:i+.18*s},t=()=>{if(!this._targets)return void(this._counterRaf=null);const i=this._targets,s=e(this._solarDisp,i.solar),r=e(this._battDisp,i.batt),a=e(this._homeDisp,i.home),o=e(this._evDisp,i.ev),n=e(this._gridDisp,i.grid),l=s===i.solar&&r===i.batt&&a===i.home&&o===i.ev&&n===i.grid&&this._gridDispMode===i.gridMode;this._solarDisp=s,this._battDisp=r,this._homeDisp=a,this._evDisp=o,this._gridDisp=n,this._gridDispMode=i.gridMode,this._counterRaf=l?null:requestAnimationFrame(t)};this._counterRaf=requestAnimationFrame(t)}firstUpdated(){this._resizeObserver=new ResizeObserver(e=>{this._resizeTimeout&&clearTimeout(this._resizeTimeout),this._resizeTimeout=setTimeout(()=>{for(const t of e){const e=t.contentRect.width<500;e!==this._compact&&(this._compact=e,this._sunSparkSig="",this._lastDiagKey="",this.requestUpdate())}},100)}),this._resizeObserver.observe(this),this._intersectionObserver=new IntersectionObserver(e=>{this._visible=e[0].isIntersecting;const t=this.renderRoot.querySelector("svg");t&&(t.style.animationPlayState=this._visible?"running":"paused")},{threshold:.01}),this._intersectionObserver.observe(this)}disconnectedCallback(){super.disconnectedCallback(),this._resizeObserver&&(this._resizeObserver.disconnect(),this._resizeObserver=null),this._intersectionObserver&&(this._intersectionObserver.disconnect(),this._intersectionObserver=null),clearTimeout(this._resizeTimeout),this._counterRaf&&(cancelAnimationFrame(this._counterRaf),this._counterRaf=null)}updated(e){if(super.updated(e),!this._hass)return;const t=this.renderRoot.querySelector("#sun-arc-path");if(!t)return;const i=this._getLayout(),s=this._computeSunPose();try{const e=t.getTotalLength(),r=t.getPointAtLength(s.pos*e),a=r.x-i.sunX,o=r.y-i.sunY,n=`translate(${a.toFixed(1)},${o.toFixed(1)}) translate(${i.sunX},${i.sunY}) scale(${s.scale.toFixed(2)}) translate(${(-i.sunX).toFixed(1)},${(-i.sunY).toFixed(1)})`,l=s.isNight?`translate(${a.toFixed(1)},${o.toFixed(1)})`:"",c=r.x.toFixed(1),d=(r.y+i.sunR*s.scale+16).toFixed(1),p=+r.x.toFixed(1),h=+r.y.toFixed(1);if(this._sunTransform===n&&this._moonTransform===l&&this._sunPowerX===c&&this._sunPowerY===d&&this._sunPtX===p&&this._sunPtY===h)return;this._sunTransform=n,this._moonTransform=l,this._sunPowerX=c,this._sunPowerY=d,this._sunPtX=p,this._sunPtY=h}catch(e){}}_computeSunPose(){const e=this._hass?.states["sun.sun"],t=(e&&parseFloat(e.attributes?.elevation)||-90)<0,i=this._val("solar_power"),s=e?.attributes;let r=.5;if(s){const e=s.next_rising?new Date(s.next_rising).getTime():0,i=s.next_setting?new Date(s.next_setting).getTime():0,a=Date.now();if(!t&&e&&i){const t=e-864e5,s=i-t;s>0&&(r=(a-t)/s)}else r=e&&a<e?0:1;r=Math.max(.06,Math.min(.94,r))}return{pos:r,scale:t?.7:.7+.6*Math.min(1,i/1e4),isNight:t,solar:i}}static get styles(){return a`
            :host { display: block; }
            ha-card { overflow: hidden; padding: 0; background: transparent !important; }
            svg { width: 100%; display: block; }
            .flow-group { transition: opacity 0.8s cubic-bezier(0.4,0,0.2,1); }
            .clickable { cursor: pointer; pointer-events: bounding-box; }
            .clickable:hover { filter: brightness(1.2); }
            text { font-variant-numeric: tabular-nums; }
            @media (prefers-reduced-motion: reduce) {
                .flow-group { transition: none; }
                animate, animateMotion { display: none; }
            }
        `}render(){if(!this._config)return q;const e=this._getLayout(),t=this._compact,i="'Segoe UI','Roboto',sans-serif",s=e.font.label,r=e.font.value,a=e.font.sub,o=this._flowSolar(),{gridImport:n,gridExport:l}=this._flowGridPair(),c=this._flowEv();let d,p;this._entities?.battery?.charge||this._entities?.battery?.discharge?(d=this._flowBattery(),p=!1):(({value:d,stale:p}=this._readWithHold("battery_power","this._lastBattPower",6e4)),this._entities?.battery?.reverse&&(d=-d));const{value:h,stale:_}=this._readWithHold("battery_soc","this._lastBattSoc",6e4),g=p||_,u=Math.max(0,d),f=Math.max(0,-d),m=this._flowHome(o,n,l,u,f,c),y=this._computeSunPose(),{isNight:v}=y,x=v?.3:.85,b=o>50?Math.min(1,.3+o/5e3):0,$=this._hass?.states["sun.sun"]?.attributes,w=this._hass?.config?.time_zone||void 0,k=$?.next_rising?ue($.next_rising,w):"",S=$?.next_setting?ue($.next_setting,w):"",C=e.B.r/50,z=64*C,M=z-12*C,E=e.B.cy-z/2+8*C,D=Math.max(0,Math.min(M,M*(h/100))),F=E+M-D,I=u>10?"#f06292":"url(#battFillGrad)",B=u>10,N=l>n?"#8353d1":"#488fc2",A=l>10&&l>n?this._t("exporting"):n>10?this._t("importing"):"",T=l>10&&l>n?"#8353d1":"#488fc2",P=u>10?"#f06292":"#4db6ac",R=u>10?this._t("charging"):f>10?this._t("discharging"):"",L=u>10?"#f06292":"#4db6ac",O="on"===this._hass?.states["binary_sensor.sem_ev_connected"]?.state;let U="",H="#8DC892";"on"===this._hass?.states["binary_sensor.sem_ev_charging"]?.state||c>10?(U=this._t("charging"),H="#8DC892"):O&&(U=this._t("connected")||"Verbunden",H="rgba(141,200,146,0.6)");const G=this._t("today"),K=`${G} ${this._valStr("daily_solar_energy")} kWh`,V=this._val("forecast_today_kwh"),Y=V>0?`☀ ${V.toFixed(1)} kWh ${this._t("forecast")||"Forecast"}`:"",X=`${G} ${this._valStr("daily_ev_energy")} kWh`,Z=`${G} ${this._val("daily_home_energy").toFixed(1)} kWh`,J=`+${this._val("daily_battery_charge_energy").toFixed(1)} / -${this._val("daily_battery_discharge_energy").toFixed(1)} kWh`,Q=`↓${this._val("daily_grid_import_energy").toFixed(1)} / ↑${this._val("daily_grid_export_energy").toFixed(1)} kWh`,ee=this._valStr("inverter_temperature"),te=""===ee||isNaN(parseFloat(ee))?"":`${parseFloat(ee).toFixed(0)}°C`,ie=this._valStr("charging_state"),se=t?22:30,re=ie.length>se?ie.substring(0,se-1)+"…":ie,ae=[],oe=["solar_power","grid_import_power","grid_export_power"];this._showBattery&&oe.push("battery_power","battery_soc"),this._showEv&&oe.push("ev_power");for(const e of oe){const t=this._eid(e);if(!t){"prefix"===this._mode&&ae.push(e);continue}const i=this._hass?.states[t];i&&"unavailable"!==i.state&&"unknown"!==i.state||ae.push(e)}const ne=ge(this._solarDisp??0),le=(u>10?"↑ ":f>10?"↓ ":"")+ge(this._battDisp??0),ce=ge(this._homeDisp??0),de=ge(this._evDisp??0),pe=this._gridDispMode?`${this._gridDispMode} ${ge(this._gridDisp??0)}`:ge(0),he="↑"===this._gridDispMode?"#8353d1":"#488fc2",_e=xe(this._hass,this._prefix),me=o>10,ye=Math.abs(d)>10,ve=d<0,$e=u>10?"#f06292":"#4db6ac",we=n>10||l>10,ke=n>l,Se=l>n?"#8353d1":"#488fc2",Ce=m>10,ze=c>10;return W`
            <ha-card>
                <style>${be}</style>
                ${_e.length>=2?W`
                    <div class="pv-strings-row">
                        ${_e.map(e=>W`
                            <div class="pv-chip"
                                 title="${e.entityId}"
                                 data-entity="${e.entityId}"
                                 @click=${()=>this._fireMoreInfo?.(e.entityId)}>
                                <span class="pv-chip-label">${e.name}</span>
                                <span class="pv-chip-value">${(Math.abs(e.watts)/1e3).toFixed(2)} kW</span>
                            </div>
                        `)}
                    </div>
                `:q}
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="${e.vb}"
                     style="background:transparent;overflow:hidden"
                     role="img" aria-label="Solar energy system power flow diagram">
                    <defs>
                        <radialGradient id="bgGrad" cx="50%" cy="40%" r="65%">
                            <stop offset="0%" stop-color="rgba(150,202,238,0.06)"/>
                            <stop offset="100%" stop-color="rgba(0,0,0,0)"/>
                        </radialGradient>
                        <pattern id="dotGrid" width="40" height="40" patternUnits="userSpaceOnUse">
                            <circle cx="20" cy="20" r="0.6" fill="rgba(128,128,128,0.07)"/>
                        </pattern>

                        ${this._glowFilter("glowSolar","#ff9800",10)}
                        ${this._glowFilter("glowBattery","#4db6ac",8)}
                        ${this._glowFilter("glowGrid","#488fc2",8)}
                        ${this._glowFilter("glowHome","#5BC8D8",12)}
                        ${this._glowFilter("glowEV","#8DC892",8)}
                        ${this._glowFilter("glowInverter","#96CAEE",6)}
                        ${this._glowFilter("glowSun","#FCD170",14)}

                        <linearGradient id="panelBlue" x1="0%" y1="0%" x2="100%" y2="100%">
                            <stop offset="0%" stop-color="#1565C0" stop-opacity="0.9"/>
                            <stop offset="50%" stop-color="#1976D2" stop-opacity="0.8"/>
                            <stop offset="100%" stop-color="#0D47A1" stop-opacity="0.95"/>
                        </linearGradient>
                        <linearGradient id="panelBlue2" x1="0%" y1="0%" x2="100%" y2="100%">
                            <stop offset="0%" stop-color="#1E88E5" stop-opacity="0.85"/>
                            <stop offset="100%" stop-color="#1565C0" stop-opacity="0.9"/>
                        </linearGradient>
                        <linearGradient id="panelReflect" x1="0%" y1="0%" x2="0%" y2="100%">
                            <stop offset="0%" stop-color="rgba(255,255,255,0.18)"/>
                            <stop offset="100%" stop-color="rgba(255,255,255,0)"/>
                        </linearGradient>

                        <linearGradient id="battBody" x1="0%" y1="0%" x2="100%" y2="0%">
                            <stop offset="0%" stop-color="#1a2e2c"/>
                            <stop offset="100%" stop-color="#1f3835"/>
                        </linearGradient>
                        <linearGradient id="battFillGrad" x1="0%" y1="100%" x2="0%" y2="0%">
                            <stop offset="0%" stop-color="#4db6ac"/>
                            <stop offset="100%" stop-color="#80cbc4"/>
                        </linearGradient>

                        <linearGradient id="roofGrad" x1="0%" y1="0%" x2="0%" y2="100%">
                            <stop offset="0%" stop-color="#c62828"/>
                            <stop offset="100%" stop-color="#b71c1c"/>
                        </linearGradient>
                        <linearGradient id="wallGrad" x1="0%" y1="0%" x2="0%" y2="100%">
                            <stop offset="0%" stop-color="#37474F"/>
                            <stop offset="100%" stop-color="#263238"/>
                        </linearGradient>
                        <radialGradient id="windowGlow" cx="50%" cy="50%" r="50%">
                            <stop offset="0%" stop-color="#FFF9C4" stop-opacity="0.9"/>
                            <stop offset="100%" stop-color="#F9A825" stop-opacity="0.3"/>
                        </radialGradient>

                        <linearGradient id="poleGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                            <stop offset="0%" stop-color="#5c7a9b"/>
                            <stop offset="50%" stop-color="#6d8fad"/>
                            <stop offset="100%" stop-color="#5c7a9b"/>
                        </linearGradient>

                        <linearGradient id="invGrad" x1="0%" y1="0%" x2="0%" y2="100%">
                            <stop offset="0%" stop-color="#1a2740"/>
                            <stop offset="100%" stop-color="#0f1820"/>
                        </linearGradient>

                        <linearGradient id="carGrad" x1="0%" y1="0%" x2="0%" y2="100%">
                            <stop offset="0%" stop-color="#2e5a3c"/>
                            <stop offset="100%" stop-color="#1b3b27"/>
                        </linearGradient>

                        <radialGradient id="sunGradInner" cx="50%" cy="50%" r="50%">
                            <stop offset="0%" stop-color="#FFF9C4"/>
                            <stop offset="60%" stop-color="#FCD170"/>
                            <stop offset="100%" stop-color="#F7941E"/>
                        </radialGradient>

                        ${null!=this._sunPtX&&o>50?this._sparkWavePath(e):q}
                    </defs>

                    <rect width="100%" height="100%" fill="url(#bgGrad)"/>
                    <rect width="100%" height="100%" fill="url(#dotGrid)"/>

                    <!-- Sun arc group -->
                    <g>
                        <path id="sun-arc-path" d="${e.sunArc}" fill="none" stroke="rgba(252,209,112,0.12)"
                              stroke-width="2" stroke-dasharray="4,8"/>
                        <text x="${e.sunRisingX}" y="${e.sunLabelY}"
                              text-anchor="middle" font-family="${i}" font-size="${a}"
                              fill="#FCD170" opacity="0.45">${k}</text>
                        <text x="${e.sunSettingX}" y="${e.sunLabelY}"
                              text-anchor="middle" font-family="${i}" font-size="${a}"
                              fill="#FCD170" opacity="0.45">${S}</text>

                        <g filter="url(#glowSun)" style="opacity:${x}"
                           transform="${this._sunTransform??""}">
                            <circle cx="${e.sunX}" cy="${e.sunY}" r="${e.sunR+6}"
                                    fill="rgba(252,209,112,0.15)"/>
                            ${this._sunRays(e.sunX,e.sunY,e.sunR)}
                            <circle cx="${e.sunX}" cy="${e.sunY}" r="${e.sunR}"
                                    fill="url(#sunGradInner)"/>
                            <ellipse cx="${e.sunX-.25*e.sunR}" cy="${e.sunY-.28*e.sunR}"
                                     rx="${.35*e.sunR}" ry="${.22*e.sunR}"
                                     fill="rgba(255,255,255,0.35)"/>
                        </g>

                        <g style="display:${v?"block":"none"}"
                           transform="${this._moonTransform??""}">
                            <circle cx="${e.sunX}" cy="${e.sunY}" r="${e.sunR}" fill="#1a2540"/>
                            <circle cx="${e.sunX+.38*e.sunR}" cy="${e.sunY-.22*e.sunR}"
                                    r="${.78*e.sunR}" fill="#0d1a30"/>
                            <circle cx="${e.sunX}" cy="${e.sunY}" r="${e.sunR}"
                                    fill="none" stroke="rgba(200,220,255,0.5)" stroke-width="1"/>
                        </g>

                        <g style="display:${v?"block":"none"}" fill="rgba(200,220,255,0.6)">
                            <circle cx="${e.starX[0]}" cy="${e.starY[0]}" r="1.2"/>
                            <circle cx="${e.starX[1]}" cy="${e.starY[1]}" r="0.9"/>
                            <circle cx="${e.starX[2]}" cy="${e.starY[2]}" r="1.4"/>
                            <circle cx="${e.starX[3]}" cy="${e.starY[3]}" r="0.8"/>
                            <circle cx="${e.starX[4]}" cy="${e.starY[4]}" r="1.1"/>
                        </g>

                        <text x="${this._sunPowerX??e.sunX}" y="${this._sunPowerY??e.sunY+e.sunR+14}"
                              text-anchor="middle" font-family="${i}" font-size="${a}"
                              fill="#FCD170" opacity="0.7" font-weight="600">${o>10?ge(o):""}</text>

                        <g style="opacity:${b}">
                            ${null!=this._sunPtX&&o>50?this._renderSunSpark(o):q}
                        </g>
                    </g>

                    <!-- Static dashed flow tracks -->
                    <path d="${e.paths.solar}"   fill="none" stroke="#ff9800" stroke-width="2"
                          stroke-dasharray="5,7" opacity="0.22"/>
                    <path d="${e.paths.home}"    fill="none" stroke="#5BC8D8" stroke-width="2"
                          stroke-dasharray="5,7" opacity="0.22"/>
                    ${this._showBattery?j`<path d="${e.paths.battery}" fill="none" stroke="#4db6ac" stroke-width="2"
                          stroke-dasharray="5,7" opacity="0.22"/>`:q}
                    <path d="${e.paths.grid}"    fill="none" stroke="#488fc2" stroke-width="2"
                          stroke-dasharray="5,7" opacity="0.22"/>
                    ${this._showEv?j`<path d="${e.paths.ev}" fill="none" stroke="#8DC892" stroke-width="2"
                          stroke-dasharray="5,7" opacity="0.22"/>`:q}

                    <!-- Flow animation groups -->
                    <g class="flow-group" style="opacity:${me?1:0}">
                        ${this._renderFlow(!1,"#ff9800",fe(o),e.paths.solar,2)}
                    </g>
                    ${this._showBattery?j`<g class="flow-group" style="opacity:${ye?1:0}">
                        ${this._renderFlow(ve,$e,fe(d),e.paths.battery,3)}
                    </g>`:q}
                    <g class="flow-group" style="opacity:${we?1:0}">
                        ${this._renderFlow(ke,Se,fe(n||l),e.paths.grid,3)}
                    </g>
                    <g class="flow-group" style="opacity:${Ce?1:0}">
                        ${this._renderFlow(!1,"#5BC8D8",fe(m),e.paths.home,2)}
                    </g>
                    ${this._showEv?j`<g class="flow-group" style="opacity:${ze?1:0}">
                        ${this._renderFlow(!1,"#8DC892",fe(c),e.paths.ev,3)}
                    </g>`:q}

                    <!-- Solar panel -->
                    <g filter="url(#glowSolar)" class="clickable" @click=${()=>this._showMoreInfo("solar_power")}>
                        ${this._illustrationSolarPanel(e.S.cx,e.S.cy,e.S.r)}
                    </g>
                    <text x="${e.S.cx}" y="${e.S.labelY}" text-anchor="middle"
                          font-family="${i}" font-size="${s}" font-weight="700"
                          fill="#ff9800" letter-spacing="0.5">${this._t("solar")}</text>
                    <text x="${e.S.cx}" y="${e.S.labelY+1.1*r}" class="clickable"
                          @click=${()=>this._showMoreInfo("solar_power")}
                          text-anchor="middle" font-family="${i}" font-size="${r}"
                          font-weight="800" fill="#ff9800">${ne}</text>
                    <text x="${e.S.cx}" y="${e.S.labelY+1.1*r+a+3}" class="clickable"
                          @click=${()=>this._showMoreInfo("daily_solar_energy")}
                          text-anchor="middle" font-family="${i}" font-size="${a+1}"
                          fill="#ff9800" opacity="0.6" font-weight="600">${K}</text>
                    <text x="${e.S.cx}" y="${e.S.labelY+1.1*r+2*(a+3)}" class="clickable"
                          @click=${()=>this._showMoreInfo("forecast_today_kwh")}
                          text-anchor="middle" font-family="${i}" font-size="${a}"
                          fill="#ff9800" opacity="0.4" font-weight="500">${Y}</text>

                    <!-- Inverter -->
                    <g filter="url(#glowInverter)">
                        ${this._illustrationInverter(e.I.cx,e.I.cy,e.I.r)}
                    </g>
                    <text x="${e.I.cx}" y="${e.I.cy+e.I.r+14}"
                          text-anchor="middle" font-family="${i}" font-size="${a}"
                          fill="#96CAEE" opacity="0.6" font-weight="600">${te}</text>
                    <text x="${e.I.cx}" y="${e.I.cy+e.I.r+14+a+2}"
                          text-anchor="middle" font-family="${i}" font-size="${a-1}"
                          fill="#96CAEE" opacity="0.35">${re}</text>

                    <!-- Battery (omitted entirely when show_battery: false,
                         #614 — the ghost-node class's battery sibling).
                         Group opacity fades to 0.35 if both
                         battery_soc and battery_power have been
                         unavailable for >60 s (Huawei modbus hard
                         dropout). Brief flickers (<60 s) are absorbed
                         by '_readWithHold' upstream so the user
                         doesn't see a visual emergency. (NEVER put
                         backticks inside this lit template's COMMENTS:
                         they terminate the template literal and the whole
                         card renders blank, #488.) -->
                    ${this._showBattery?j`<g filter="url(#glowBattery)" class="clickable"
                       opacity="${g?.35:1}"
                       @click=${()=>this._showMoreInfo("battery_soc")}>
                        ${this._illustrationBattery(e.B.cx,e.B.cy,e.B.r,D,F,I,B,h)}
                    </g>
                    <text x="${e.B.cx}" y="${e.B.labelY}" text-anchor="middle"
                          font-family="${i}" font-size="${s}" font-weight="700"
                          fill="#4db6ac" letter-spacing="0.5">${this._t("battery")}</text>
                    <text x="${e.B.cx}" y="${e.B.labelY+1*r}" class="clickable"
                          @click=${()=>this._showMoreInfo("battery_power")}
                          text-anchor="middle" font-family="${i}" font-size="${r}"
                          font-weight="800" fill="${P}"
                          opacity="${g?.4:1}">${g?"— W":le}</text>
                    <text x="${e.B.cx}" y="${e.B.labelY+1*r+s}"
                          text-anchor="middle" font-family="${i}" font-size="${s}"
                          fill="${L}" opacity="0.6">${g?this._t("sensor_unavailable"):R}</text>
                    <text x="${e.B.cx}" y="${e.B.labelY+1*r+s+a+2}" class="clickable"
                          @click=${()=>this._showMoreInfo("daily_battery_charge_energy")}
                          text-anchor="middle" font-family="${i}" font-size="${a+1}"
                          fill="#4db6ac" opacity="0.6" font-weight="600">${J}</text>`:q}

                    <!-- Grid -->
                    <g filter="url(#glowGrid)" class="clickable" @click=${()=>this._showMoreInfo("grid_import_power")}>
                        ${this._illustrationGrid(e.G.cx,e.G.cy,e.G.r)}
                    </g>
                    <text x="${e.G.cx}" y="${e.G.labelY}" text-anchor="middle"
                          font-family="${i}" font-size="${s}" font-weight="700"
                          fill="${N}" letter-spacing="0.5">${this._t("grid")}</text>
                    <text x="${e.G.cx}" y="${e.G.labelY+r}" class="clickable"
                          @click=${()=>this._showMoreInfo("grid_power")}
                          text-anchor="middle" font-family="${i}" font-size="${r}"
                          font-weight="800" fill="${he}">${pe}</text>
                    <text x="${e.G.cx}" y="${e.G.labelY+r+s+1}"
                          text-anchor="middle" font-family="${i}" font-size="${s}"
                          fill="${T}" opacity="0.6">${A}</text>
                    <text x="${e.G.cx}" y="${e.G.labelY+r+s+a+4}" class="clickable"
                          @click=${()=>this._showMoreInfo("daily_grid_import_energy")}
                          text-anchor="middle" font-family="${i}" font-size="${a+1}"
                          fill="#488fc2" opacity="0.6" font-weight="600">${Q}</text>

                    <!-- House -->
                    <g filter="url(#glowHome)" class="clickable" @click=${()=>this._showMoreInfo("home_consumption_power")}>
                        ${this._illustrationHouse(e.H.cx,e.H.cy,e.H.r)}
                    </g>
                    <text x="${e.H.cx}" y="${e.H.labelY}" text-anchor="middle"
                          font-family="${i}" font-size="${s}" font-weight="700"
                          fill="#5BC8D8" letter-spacing="0.5">${this._t("home")}</text>
                    <text x="${e.H.cx}" y="${e.H.labelY+1.1*r}" class="clickable"
                          @click=${()=>this._showMoreInfo("home_consumption_power")}
                          text-anchor="middle" font-family="${i}" font-size="${r}"
                          font-weight="800" fill="#5BC8D8">${ce}</text>
                    <text x="${e.H.cx}" y="${e.H.labelY+1.1*r+a+3}" class="clickable"
                          @click=${()=>this._showMoreInfo("daily_home_energy")}
                          text-anchor="middle" font-family="${i}" font-size="${a+1}"
                          fill="#5BC8D8" opacity="0.6" font-weight="600">${Z}</text>

                    <!-- EV (omitted entirely when show_ev: false, #595) -->
                    ${this._showEv?j`<g filter="url(#glowEV)" class="clickable" @click=${()=>this._showMoreInfo("ev_power")}>
                        ${this._illustrationEV(e.E.cx,e.E.cy,e.E.r)}
                    </g>
                    <text x="${e.E.cx}" y="${e.E.labelY}" text-anchor="middle"
                          font-family="${i}" font-size="${s}" font-weight="700"
                          fill="#8DC892" letter-spacing="0.5">${this._t("ev_charging")}</text>
                    <text x="${e.E.cx}" y="${e.E.labelY+1*r}" class="clickable"
                          @click=${()=>this._showMoreInfo("ev_power")}
                          text-anchor="middle" font-family="${i}" font-size="${r}"
                          font-weight="800" fill="#8DC892">${de}</text>
                    <text x="${e.E.cx}" y="${e.E.labelY+1*r+s}"
                          text-anchor="middle" font-family="${i}" font-size="${s}"
                          fill="${H}" opacity="0.6">${U}</text>
                    <text x="${e.E.cx}" y="${e.E.labelY+1*r+s+a+2}" class="clickable"
                          @click=${()=>this._showMoreInfo("daily_ev_energy")}
                          text-anchor="middle" font-family="${i}" font-size="${a+1}"
                          fill="#8DC892" opacity="0.6" font-weight="600">${X}</text>`:q}

                    <!-- Device strip (desktop only) -->
                    ${t?q:this._renderDeviceStrip(e.H)}

                    <!-- Entity status indicator -->
                    ${ae.length>0?W`
                        <foreignObject x="${t?8:10}" y="${e.statusY}" width="220" height="22">
                            <div xmlns="http://www.w3.org/1999/xhtml"
                                 style="font-family:'Segoe UI','Roboto',sans-serif;font-size:11px;color:#ef5350;opacity:0.75;white-space:nowrap">⚠ ${ae.length} ${this._t("sensor_unavailable")}</div>
                        </foreignObject>
                    `:q}

                    <text x="${e.wmX}" y="${e.wmY}" text-anchor="end"
                          font-family="${i}" font-size="9" font-weight="300"
                          letter-spacing="2.5" fill="rgba(255,255,255,0.06)">SEM</text>
                </svg>
                ${t?this._renderDeviceChips():q}
            </ha-card>
        `}_illustrationSolarPanel(e,t,i){const s=i/50,r=86*s,a=58*s,o=e-r/2,n=t-a/2-4*s,l=r/3,c=a/2,d=6*s,p=12*s;return j`
            <circle cx="${e}" cy="${t}" r="${i+4}" fill="none"
                    stroke="#ff9800" stroke-width="1.2" opacity="0.25"/>

            <line x1="${o+d}" y1="${n+a}" x2="${o+d-4*s}" y2="${n+a+p}"
                  stroke="#ff9800" stroke-width="${2*s}" stroke-linecap="round" opacity="0.7"/>
            <line x1="${o+r-d}" y1="${n+a}" x2="${o+r-d+4*s}" y2="${n+a+p}"
                  stroke="#ff9800" stroke-width="${2*s}" stroke-linecap="round" opacity="0.7"/>
            <line x1="${o+r/2}" y1="${n+a}" x2="${o+r/2}" y2="${n+a+.8*p}"
                  stroke="#ff9800" stroke-width="${1.5*s}" stroke-linecap="round" opacity="0.5"/>
            <line x1="${o+d-6*s}" y1="${n+a+p}"
                  x2="${o+r-d+6*s}" y2="${n+a+p}"
                  stroke="#ff9800" stroke-width="${2.5*s}" stroke-linecap="round" opacity="0.6"/>

            <line x1="${o}" y1="${n+.52*a}" x2="${o+r}" y2="${n+.52*a}"
                  stroke="#ff9800" stroke-width="${2*s}" opacity="0.5"/>
            <line x1="${o}" y1="${n}" x2="${o+r}" y2="${n}"
                  stroke="#ff9800" stroke-width="${2*s}" opacity="0.5"/>

            <rect x="${o}"        y="${n}"      width="${l}" height="${c}" fill="url(#panelBlue)"  rx="${1*s}"/>
            <rect x="${o+l}"   y="${n}"      width="${l}" height="${c}" fill="url(#panelBlue2)" rx="${1*s}"/>
            <rect x="${o+2*l}" y="${n}"      width="${l}" height="${c}" fill="url(#panelBlue)"  rx="${1*s}"/>
            <rect x="${o}"        y="${n+c}" width="${l}" height="${c}" fill="url(#panelBlue2)" rx="${1*s}"/>
            <rect x="${o+l}"   y="${n+c}" width="${l}" height="${c}" fill="url(#panelBlue)"  rx="${1*s}"/>
            <rect x="${o+2*l}" y="${n+c}" width="${l}" height="${c}" fill="url(#panelBlue2)" rx="${1*s}"/>

            <line x1="${o+l}"   y1="${n}" x2="${o+l}"   y2="${n+a}" stroke="rgba(0,0,0,0.4)" stroke-width="${1.5*s}"/>
            <line x1="${o+2*l}" y1="${n}" x2="${o+2*l}" y2="${n+a}" stroke="rgba(0,0,0,0.4)" stroke-width="${1.5*s}"/>
            <line x1="${o}" y1="${n+c}" x2="${o+r}" y2="${n+c}" stroke="rgba(0,0,0,0.4)" stroke-width="${1.5*s}"/>
            ${[0,1,2].map(e=>j`
                <line x1="${o+e*l+l/3}"   y1="${n}" x2="${o+e*l+l/3}"   y2="${n+a}" stroke="rgba(0,0,0,0.2)" stroke-width="${.7*s}"/>
                <line x1="${o+e*l+2*l/3}" y1="${n}" x2="${o+e*l+2*l/3}" y2="${n+a}" stroke="rgba(0,0,0,0.2)" stroke-width="${.7*s}"/>
            `)}
            <line x1="${o}" y1="${n+c/3}"   x2="${o+r}" y2="${n+c/3}"   stroke="rgba(0,0,0,0.18)" stroke-width="${.7*s}"/>
            <line x1="${o}" y1="${n+2*c/3}" x2="${o+r}" y2="${n+2*c/3}" stroke="rgba(0,0,0,0.18)" stroke-width="${.7*s}"/>

            <rect x="${o}" y="${n}" width="${r}" height="${a}"
                  fill="none" stroke="#ff9800" stroke-width="${2*s}" rx="${1.5*s}" opacity="0.8"/>

            <rect x="${o}" y="${n}" width="${r}" height="${.45*a}"
                  fill="url(#panelReflect)" rx="${1.5*s}" opacity="0.5"/>

            <circle cx="${e}" cy="${n+a+p+3*s}" r="${3*s}"
                    fill="#ff9800" opacity="0.6"/>
        `}_sunRays(e,t,i){const s=[];for(let r=0;r<8;r++){const a=45*r*Math.PI/180,o=i+3,n=i+.7*i,l=.18,c=a-l,d=a+l,p=e+Math.cos(c)*o,h=t+Math.sin(c)*o,_=e+Math.cos(a)*n,g=t+Math.sin(a)*n,u=e+Math.cos(d)*o,f=t+Math.sin(d)*o;s.push(j`<polygon points="${p},${h} ${_},${g} ${u},${f}"
                                    fill="#FCD170" opacity="0.85"/>`)}return s}_illustrationInverter(e,t,i){const s=i/20,r=38*s,a=28*s,o=e-r/2,n=t-a/2;return j`
            <rect x="${o}" y="${n}" width="${r}" height="${a}" rx="${4*s}"
                  fill="url(#invGrad)" stroke="#96CAEE" stroke-width="${1.5*s}" opacity="0.9"/>
            ${[0,1,2].map(e=>j`
                <line x1="${o+4*s+5*e*s}" y1="${n+3*s}" x2="${o+4*s+5*e*s}" y2="${n+7*s}"
                      stroke="#96CAEE" stroke-width="${1*s}" stroke-linecap="round" opacity="0.4"/>
            `)}
            <text x="${e-8*s}" y="${t+2*s}" font-family="'Segoe UI',sans-serif"
                  font-size="${7*s}" fill="#96CAEE" opacity="0.8" text-anchor="middle">DC</text>
            <path d="M${e-1*s},${t-4*s} L${e-3*s},${t+1*s} L${e},${t+1*s}
                     L${e},${t+5*s} L${e+2*s},${t} L${e-1*s},${t}"
                  fill="#FCD170" opacity="0.85"/>
            <text x="${e+8*s}" y="${t+2*s}" font-family="'Segoe UI',sans-serif"
                  font-size="${7*s}" fill="#96CAEE" opacity="0.8" text-anchor="middle">AC</text>
            <circle cx="${o+r-5*s}" cy="${n+4*s}" r="${2.5*s}"
                    fill="#69f0ae" opacity="0.9">
                <animate attributeName="opacity" values="0.9;0.4;0.9" dur="2.5s" repeatCount="indefinite"/>
            </circle>
            <rect x="${e-3*s}" y="${n+a}" width="${6*s}" height="${3*s}" rx="${1*s}"
                  fill="#96CAEE" opacity="0.4"/>
        `}_illustrationBattery(e,t,i,s,r,a,o,n){const l=i/50,c=40*l,d=64*l,p=e-c/2,h=t-d/2,_=8*l,g=16*l,u=c-8*l,f=d-12*l,m=p+4*l,y=h+8*l;return j`
            <circle cx="${e}" cy="${t}" r="${i+4}" fill="none"
                    stroke="#4db6ac" stroke-width="1.2" opacity="0.25"/>

            <rect x="${e-g/2}" y="${h-_}" width="${g}" height="${_}"
                  rx="${3*l}" fill="#2a4a47" stroke="#4db6ac" stroke-width="${1.5*l}" opacity="0.85"/>
            <line x1="${e-g/4}" y1="${h-_/2}"
                  x2="${e+g/4}" y2="${h-_/2}"
                  stroke="#4db6ac" stroke-width="${2*l}" stroke-linecap="round" opacity="0.8"/>
            <line x1="${e}" y1="${h-.75*_}" x2="${e}" y2="${h-.25*_}"
                  stroke="#4db6ac" stroke-width="${2*l}" stroke-linecap="round" opacity="0.8"/>

            <rect x="${p}" y="${h}" width="${c}" height="${d}" rx="${5*l}"
                  fill="url(#battBody)" stroke="#4db6ac" stroke-width="${2*l}" opacity="0.95"/>

            <rect x="${m}" y="${y}" width="${u}" height="${f}"
                  rx="${3*l}" fill="rgba(0,0,0,0.4)"/>

            <rect x="${m}" y="${r.toFixed(1)}"
                  width="${u}" height="${s.toFixed(1)}"
                  rx="${3*l}" fill="${a}" opacity="0.85"/>

            ${[1,2,3,4].map(e=>j`
                <line x1="${m}" y1="${y+f*e/5}"
                      x2="${m+u}" y2="${y+f*e/5}"
                      stroke="rgba(0,0,0,0.35)" stroke-width="${1.2*l}"/>
            `)}

            <text x="${e}" y="${o?t+15*l:t+4*l}"
                  text-anchor="middle" font-family="'Segoe UI','Roboto',sans-serif"
                  font-size="${14*l}" font-weight="900" fill="#fff"
                  stroke="rgba(0,0,0,0.6)" stroke-width="${1.5*l}" paint-order="stroke">${n.toFixed(0)}%</text>

            ${o?j`
                <g>
                    <path d="M${e-4*l},${t-9*l-8*l} L${e-7*l},${t-9*l+2*l} L${e-1*l},${t-9*l+2*l}
                             L${e-1*l},${t-9*l+10*l} L${e+6*l},${t-9*l-2*l} L${e+1*l},${t-9*l-2*l} Z"
                          fill="#FCD170" opacity="0.95"/>
                </g>
            `:q}

            <rect x="${e-10*l}" y="${h+d-5*l}" width="${20*l}" height="${5*l}"
                  rx="${2*l}" fill="#4db6ac" opacity="0.25"/>
        `}_illustrationHouse(e,t,i){const s=i/62,r=80*s,a=52*s,o=e-r/2,n=t-a/2+8*s,l=n-38*s,c=e+18*s,d=l+8*s,p=10*s,h=18*s,_=16*s,g=14*s,u=n+12*s,f=o+10*s,m=o+r-10*s-_,y=14*s,v=24*s,x=e-y/2,b=n+a-v;return j`
            <circle cx="${e}" cy="${t}" r="${i+4}" fill="none"
                    stroke="#5BC8D8" stroke-width="1.2" opacity="0.25"/>

            <rect x="${c}" y="${d-h}" width="${p}" height="${h}"
                  rx="${2*s}" fill="#455A64" stroke="#546E7A" stroke-width="${1.2*s}"/>
            <circle cx="${c+p/2}" cy="${d-h-5*s}" r="${3*s}"
                    fill="rgba(150,160,170,0.3)"/>
            <circle cx="${c+p/2+2*s}" cy="${d-h-10*s}" r="${2.5*s}"
                    fill="rgba(150,160,170,0.2)"/>

            <polygon points="${o},${n} ${o+r},${n} ${e},${l}"
                     fill="url(#roofGrad)" stroke="#c62828" stroke-width="${1.5*s}"
                     stroke-linejoin="round"/>
            <line x1="${e-18*s}" y1="${l+10*s}" x2="${e+18*s}" y2="${l+10*s}"
                  stroke="rgba(255,255,255,0.12)" stroke-width="${1*s}"/>
            <line x1="${o-3*s}" y1="${n}" x2="${o+r+3*s}" y2="${n}"
                  stroke="#7f1010" stroke-width="${3*s}" opacity="0.5"/>

            <rect x="${o}" y="${n}" width="${r}" height="${a}"
                  rx="${2*s}" fill="url(#wallGrad)"
                  stroke="#546E7A" stroke-width="${1.5*s}"/>

            <rect x="${f-2*s}" y="${u-2*s}" width="${_+4*s}" height="${g+4*s}"
                  rx="${2*s}" fill="#2d3c45" stroke="#5BC8D8" stroke-width="${1.2*s}" opacity="0.9"/>
            <rect x="${f}" y="${u}" width="${_}" height="${g}"
                  rx="${1.5*s}" fill="url(#windowGlow)" opacity="0.85"/>
            <line x1="${f+_/2}" y1="${u}" x2="${f+_/2}" y2="${u+g}"
                  stroke="rgba(50,50,60,0.6)" stroke-width="${1.2*s}"/>
            <line x1="${f}" y1="${u+g/2}" x2="${f+_}" y2="${u+g/2}"
                  stroke="rgba(50,50,60,0.6)" stroke-width="${1.2*s}"/>

            <rect x="${m-2*s}" y="${u-2*s}" width="${_+4*s}" height="${g+4*s}"
                  rx="${2*s}" fill="#2d3c45" stroke="#5BC8D8" stroke-width="${1.2*s}" opacity="0.9"/>
            <rect x="${m}" y="${u}" width="${_}" height="${g}"
                  rx="${1.5*s}" fill="url(#windowGlow)" opacity="0.85"/>
            <line x1="${m+_/2}" y1="${u}" x2="${m+_/2}" y2="${u+g}"
                  stroke="rgba(50,50,60,0.6)" stroke-width="${1.2*s}"/>
            <line x1="${m}" y1="${u+g/2}" x2="${m+_}" y2="${u+g/2}"
                  stroke="rgba(50,50,60,0.6)" stroke-width="${1.2*s}"/>

            <rect x="${x}" y="${b}" width="${y}" height="${v}"
                  rx="${2*s}" fill="#506C7F" stroke="#5BC8D8" stroke-width="${1.2*s}" opacity="0.9"/>
            <rect x="${x+.15*y}" y="${b+4*s}"
                  width="${.7*y}" height="${.35*v}"
                  rx="${1.5*s}" fill="url(#windowGlow)" opacity="0.6"/>
            <circle cx="${x+.75*y}" cy="${b+.62*v}" r="${1.5*s}"
                    fill="#FCD170" opacity="0.8"/>

            <line x1="${o+2*s}" y1="${n+4*s}" x2="${o+2*s}" y2="${n+a-2*s}"
                  stroke="rgba(255,255,255,0.06)" stroke-width="${1.5*s}"/>
        `}_illustrationGrid(e,t,i){const s=i/50,r=72*s,a=4*s,o=t-r/2+4*s,n=o+.22*r,l=o+.42*r,c=44*s,d=32*s,p=3*s;return j`
            <circle cx="${e}" cy="${t}" r="${i+4}" fill="none"
                    stroke="#488fc2" stroke-width="1.2" opacity="0.25"/>

            <polygon points="${e-a/2},${o+r}
                             ${e+a/2},${o+r}
                             ${e+.35*a},${o}
                             ${e-.35*a},${o}"
                     fill="url(#poleGrad)" stroke="#5c7a9b" stroke-width="${1*s}"/>

            <rect x="${e-8*s}" y="${o+r-4*s}"
                  width="${16*s}" height="${4*s}" rx="${2*s}"
                  fill="#5c7a9b" opacity="0.6"/>

            <rect x="${e-c/2}" y="${n-3*s}" width="${c}" height="${5*s}"
                  rx="${2*s}" fill="url(#poleGrad)" stroke="#5c7a9b" stroke-width="${.8*s}"/>
            <line x1="${e}" y1="${n+2*s}"
                  x2="${e-.4*c}" y2="${n+14*s}"
                  stroke="#5c7a9b" stroke-width="${2*s}" opacity="0.5"/>
            <line x1="${e}" y1="${n+2*s}"
                  x2="${e+.4*c}" y2="${n+14*s}"
                  stroke="#5c7a9b" stroke-width="${2*s}" opacity="0.5"/>

            <rect x="${e-d/2}" y="${l-3*s}" width="${d}" height="${5*s}"
                  rx="${2*s}" fill="url(#poleGrad)" stroke="#5c7a9b" stroke-width="${.8*s}"/>

            <circle cx="${e-c/2}" cy="${n}" r="${p}"
                    fill="#838bc5" stroke="#488fc2" stroke-width="${1*s}"/>
            <circle cx="${e+c/2}" cy="${n}" r="${p}"
                    fill="#838bc5" stroke="#488fc2" stroke-width="${1*s}"/>
            <circle cx="${e-d/2}" cy="${l}" r="${p}"
                    fill="#838bc5" stroke="#488fc2" stroke-width="${1*s}"/>
            <circle cx="${e+d/2}" cy="${l}" r="${p}"
                    fill="#838bc5" stroke="#488fc2" stroke-width="${1*s}"/>

            <path d="M${e-c/2},${n}
                     Q${e-.7*c},${n+18*s} ${e-.95*c-15*s},${n+12*s}"
                  fill="none" stroke="#488fc2" stroke-width="${1.5*s}" opacity="0.6"/>
            <path d="M${e+c/2},${n}
                     Q${e+.7*c},${n+18*s} ${e+.95*c+15*s},${n+12*s}"
                  fill="none" stroke="#488fc2" stroke-width="${1.5*s}" opacity="0.6"/>

            <path d="M${e-d/2},${l}
                     Q${e-.65*d},${l+14*s} ${e-.9*d-12*s},${l+9*s}"
                  fill="none" stroke="#488fc2" stroke-width="${1.2*s}" opacity="0.5"/>
            <path d="M${e+d/2},${l}
                     Q${e+.65*d},${l+14*s} ${e+.9*d+12*s},${l+9*s}"
                  fill="none" stroke="#488fc2" stroke-width="${1.2*s}" opacity="0.5"/>

            <path d="M${e-3*s},${l+8*s} L${e-5*s},${l+14*s}
                     L${e},${l+14*s} L${e},${l+20*s}
                     L${e+4*s},${l+11*s} L${e},${l+11*s} Z"
                  fill="#FCD170" opacity="0.6"/>
        `}_illustrationEV(e,t,i){const s=i/44,r=22*s,a=36*s,o=e-28*s,n=t-a/2,l=t+4*s,c=52*s,d=22*s,p=e+18*s-c/2,h=6*s;return j`
            <circle cx="${e}" cy="${t}" r="${i+4}" fill="none"
                    stroke="#8DC892" stroke-width="1.2" opacity="0.25"/>

            <rect x="${o}" y="${n}" width="${r}" height="${a}"
                  rx="${4*s}" fill="#1a2e22" stroke="#8DC892" stroke-width="${1.8*s}" opacity="0.95"/>
            <rect x="${o+3*s}" y="${n+4*s}" width="${r-6*s}" height="${10*s}"
                  rx="${2*s}" fill="#0a1a12" stroke="#8DC892" stroke-width="${.8*s}" opacity="0.8"/>
            <text x="${o+r/2}" y="${n+4*s+8*s}"
                  font-family="'Courier New',monospace" font-size="${5.5*s}"
                  fill="#8DC892" text-anchor="middle" opacity="0.8">AC</text>
            <path d="M${o+r/2-3*s},${n+18*s}
                     L${o+r/2-5*s},${n+25*s}
                     L${o+r/2},${n+25*s}
                     L${o+r/2},${n+32*s}
                     L${o+r/2+4*s},${n+22*s}
                     L${o+r/2},${n+22*s} Z"
                  fill="#FCD170" opacity="0.9"/>
            <circle cx="${o+r-5*s}" cy="${n+5*s}" r="${2.2*s}"
                    fill="#8DC892" opacity="0.9">
                <animate attributeName="opacity" values="0.9;0.3;0.9" dur="1.8s" repeatCount="indefinite"/>
            </circle>
            <path d="M${o+r},${n+.55*a}
                     C${o+r+10*s},${n+.55*a}
                       ${p-10*s},${l}
                       ${p},${l}"
                  fill="none" stroke="#8DC892" stroke-width="${2.5*s}"
                  stroke-linecap="round" opacity="0.7"/>
            <circle cx="${p}" cy="${l}" r="${3*s}"
                    fill="#8DC892" opacity="0.85"/>

            <rect x="${p+5*s}" y="${l}" width="${c-10*s}" height="${d/2}"
                  rx="${3*s}" fill="url(#carGrad)" stroke="#8DC892" stroke-width="${1.5*s}"/>
            <path d="M${p+12*s},${l}
                     L${p+10*s},${l-.7*d}
                     L${p+20*s},${l-.85*d}
                     L${p+c-18*s},${l-.85*d}
                     L${p+c-10*s},${l-.7*d}
                     L${p+c-8*s},${l} Z"
                  fill="url(#carGrad)" stroke="#8DC892" stroke-width="${1.5*s}"/>
            <path d="M${p+13*s},${l-2*s}
                     L${p+11*s},${l-.62*d}
                     L${p+22*s},${l-.78*d}
                     L${p+24*s},${l-2*s} Z"
                  fill="rgba(100,200,200,0.22)" stroke="rgba(100,200,200,0.4)" stroke-width="${.8*s}"/>
            <path d="M${p+c-14*s},${l-2*s}
                     L${p+c-22*s},${l-2*s}
                     L${p+c-20*s},${l-.78*d}
                     L${p+c-12*s},${l-.62*d} Z"
                  fill="rgba(100,200,200,0.22)" stroke="rgba(100,200,200,0.4)" stroke-width="${.8*s}"/>
            <circle cx="${p+14*s}" cy="${l+d/2-1*s}" r="${h}"
                    fill="#1a2525" stroke="#8DC892" stroke-width="${2*s}"/>
            <circle cx="${p+14*s}" cy="${l+d/2-1*s}" r="${.4*h}"
                    fill="#8DC892" opacity="0.5"/>
            <circle cx="${p+c-14*s}" cy="${l+d/2-1*s}" r="${h}"
                    fill="#1a2525" stroke="#8DC892" stroke-width="${2*s}"/>
            <circle cx="${p+c-14*s}" cy="${l+d/2-1*s}" r="${.4*h}"
                    fill="#8DC892" opacity="0.5"/>
            <ellipse cx="${p+c-7*s}" cy="${l+d/2-6*s}"
                     rx="${4*s}" ry="${2.5*s}"
                     fill="#FFF9C4" opacity="0.6"/>
        `}_renderFlow(e,t,i,s,r){const a=i.toFixed(1),o=String(e?28:-28),n=e?{kp:"1;0",kt:"0;1"}:null,l=[];for(let e=0;e<r;e++){const o=`-${(e/r*i).toFixed(2)}s`;l.push(j`
                <circle r="5" fill="${t}" opacity="0.12">
                    <animateMotion path="${s}" dur="${a}s" repeatCount="indefinite" calcMode="paced"
                                   keyPoints=${n?n.kp:q}
                                   keyTimes=${n?n.kt:q}
                                   begin="${o}"/>
                </circle>
                <circle r="2.5" fill="${t}" opacity="0.95">
                    <animateMotion path="${s}" dur="${a}s" repeatCount="indefinite" calcMode="paced"
                                   keyPoints=${n?n.kp:q}
                                   keyTimes=${n?n.kt:q}
                                   begin="${o}"/>
                </circle>
                <circle r="1" fill="rgba(255,255,255,0.9)" opacity="0.85">
                    <animateMotion path="${s}" dur="${a}s" repeatCount="indefinite" calcMode="paced"
                                   keyPoints=${n?n.kp:q}
                                   keyTimes=${n?n.kt:q}
                                   begin="${o}"/>
                </circle>
            `)}return j`
            <path d="${s}" fill="none" stroke="${t}" stroke-width="5"
                  stroke-dasharray="8,${20}" opacity="0.2" stroke-linecap="round">
                <animate attributeName="stroke-dashoffset" from="0" to="${o}"
                         dur="${a}s" repeatCount="indefinite"/>
            </path>
            <path d="${s}" fill="none" stroke="rgba(255,255,255,0.5)" stroke-width="1.2"
                  stroke-dasharray="6,${22}" opacity="0.45" stroke-linecap="round">
                <animate attributeName="stroke-dashoffset" from="0" to="${o}"
                         dur="${a}s" repeatCount="indefinite"/>
            </path>
            <path d="${s}" fill="none" stroke="${t}" stroke-width="2.5"
                  stroke-dasharray="8,${20}" opacity="0.65" stroke-linecap="round">
                <animate attributeName="stroke-dashoffset" from="0" to="${o}"
                         dur="${a}s" repeatCount="indefinite"/>
            </path>
            ${l}
        `}_sparkWavePath(e){const t=this._sunPtX,i=this._sunPtY,s=e.S.cx-t,r=e.S.cy-e.S.r-i,a=Math.sqrt(s*s+r*r),o=Math.max(2,Math.round(a/30)),n=this._val("solar_power"),l=6+Math.min(8,n/1e3),c=Math.atan2(r,s),d=-Math.sin(c),p=Math.cos(c),h=8*o;let _=`M${t.toFixed(1)},${i.toFixed(1)}`;for(let e=1;e<=h;e++){const a=e/h,n=t+s*a,c=i+r*a,g=Math.sin(a*o*Math.PI*2)*l;_+=` L${(n+d*g).toFixed(1)},${(c+p*g).toFixed(1)}`}return this._sparkWaveD=_,j`<path id="spark-wave" d="${_}" fill="none"
                         stroke="rgba(255,200,60,0.12)" stroke-width="2.5" stroke-linecap="round"
                         filter="url(#glowSun)"/>`}_renderSunSpark(e){const t=12-7*Math.min(1,e/1e4),i=3+Math.floor(Math.min(3,e/3e3)),s=`${t.toFixed(0)}:${i}`;if(this._sunSparkSig!==s){this._sunSparkSig=s,this._sunSparkProps=[];for(let e=0;e<i;e++)this._sunSparkProps.push({kind:e%2==0?"gold":"white",r:1.5+2*Math.random(),opacity:.4+.5*Math.random(),dur:t*(.7+.6*Math.random()),delay:Math.random()*t})}const r=this._sparkWaveD;return this._sunSparkProps.map(e=>"gold"===e.kind?j`
            <circle r="${e.r.toFixed(1)}" fill="rgba(255,220,60,${e.opacity.toFixed(2)})" filter="url(#glowSun)">
                <animateMotion path="${r}" dur="${e.dur.toFixed(1)}s" repeatCount="indefinite" calcMode="paced"
                               begin="-${e.delay.toFixed(1)}s"/>
            </circle>
        `:j`
            <circle r="${(.6*e.r).toFixed(1)}" fill="rgba(255,255,230,${e.opacity.toFixed(2)})">
                <animateMotion path="${r}" dur="${e.dur.toFixed(1)}s" repeatCount="indefinite" calcMode="paced"
                               begin="-${e.delay.toFixed(1)}s"/>
            </circle>
        `)}_collectDevices(){const e=this._eid("controllable_devices_count"),t=e?this._hass?.states[e]:void 0;return t?.attributes?.devices?Object.entries(t.attributes.devices).filter(([,e])=>"ev_charger"!==e.device_type&&"battery"!==e.device_type).map(([e,t])=>{const i=t.power_entity?this._hass.states[t.power_entity]:null,s=i?parseFloat(i.state)||0:t.current_power||0;return{id:e,...t,power:s,name:this._localizedDeviceName(e,t)}}).sort((e,t)=>t.power-e.power).slice(0,3):[]}_localizedDeviceName(e,t){const i={heat_pump:"device_heat_pump",hot_water:"device_hot_water"},s={heat_pump:"Heat Pump",hot_water:"Hot Water"}[e];if(s&&(t.name||"").trim()===s){const t=this._t(i[e]);if(t)return t}return t.name||e}_renderDeviceChips(){const e=this._collectDevices();return e.length?W`
            <div style="display:flex;gap:8px;padding:0 14px 14px;">
                ${e.map((e,t)=>{const i=_e,s=e.is_on||e.power>5;let r=e.name||e.id;return r.length>14&&(r=r.substring(0,13)+"…"),W`
                        <div class="${e.power_entity?"clickable":""}"
                             @click=${()=>e.power_entity&&this._fireMoreInfo(e.power_entity)}
                             style="flex:1;display:flex;flex-direction:column;align-items:center;gap:1px;
                                    padding:7px 4px;border-radius:12px;
                                    border:1px solid ${i}${s?"":"55"};
                                    background:rgba(128,128,128,${s?.07:.03});">
                            <svg viewBox="-16 -16 32 32" width="22" height="22" style="opacity:${s?1:.55}">
                                <g stroke="${i}" fill="none" stroke-width="1.6"
                                   stroke-linecap="round" stroke-linejoin="round">
                                    ${this._deviceIcon(e.device_type,e.name||e.id)}
                                </g>
                            </svg>
                            <div style="font-size:10px;color:${i};font-weight:600;opacity:${s?1:.85};
                                        white-space:nowrap;overflow:hidden;max-width:100%">${r}</div>
                            <div style="font-size:11px;color:${i};font-weight:800;opacity:${s?1:.85}">
                                ${s?ge(e.power):this._t("off")}</div>
                        </div>`})}
            </div>`:q}_fireMoreInfo(e){this.dispatchEvent(new CustomEvent("hass-more-info",{bubbles:!0,composed:!0,detail:{entityId:e}}))}_renderDeviceStrip(e){const t=this._collectDevices();if(!t.length)return q;const i="'Segoe UI','Roboto',sans-serif";return t.map((t,s)=>{let r=(t.name||t.id).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");r.length>22&&(r=r.substring(0,21)+"…");const a=_e,o=t.is_on||t.power>5,n=310+50*s,l=540,c=`M${e.cx+e.r},${e.cy+10+8*s} C${e.cx+e.r+40},${e.cy+30+15*s} 510,${n-10} 524,${n}`,d=t.power>5?j`
                <circle r="1.5" fill="${a}" opacity="0.8">
                    <animateMotion path="${c}" dur="${fe(t.power).toFixed(1)}s" repeatCount="indefinite" calcMode="paced"/>
                </circle>
            `:q;return j`
                <path d="${c}" fill="none" stroke="${a}" stroke-width="1"
                      stroke-dasharray="3,5" opacity="${o?.3:.1}"/>
                ${d}
                <circle cx="${l}" cy="${n}" r="${14}" fill="rgba(128,128,128,${o?.06:.02})"
                        stroke="${a}" stroke-width="0.8" opacity="${o?.7:.3}"/>
                <g transform="translate(${l},${n}) scale(0.7)" stroke="${a}" fill="none"
                   opacity="${o?.6:.25}" stroke-width="1.3" stroke-linecap="round">
                    ${this._deviceIcon(t.device_type,t.name||t.id)}
                </g>
                <text x="${560}" y="${n-2}" font-family="${i}" font-size="10"
                      font-weight="500" fill="${a}" opacity="0.85">${r}</text>
                <text x="${560}" y="${n+11}" font-family="${i}" font-size="10"
                      font-weight="700" fill="${a}" opacity="${o?.95:.75}">${ge(t.power)}</text>
            `})}_glowFilter(e,t,i){return j`<filter id="${e}" x="-35%" y="-35%" width="170%" height="170%">
            <feGaussianBlur stdDeviation="${i}" result="blur"/>
            <feFlood flood-color="${t}" flood-opacity="0.28"/>
            <feComposite in2="blur" operator="in"/>
            <feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge>
        </filter>`}_showMoreInfo(e){const t=this._eid(e);t&&this.dispatchEvent(new CustomEvent("hass-more-info",{bubbles:!0,composed:!0,detail:{entityId:t}}))}_getLayout(){return this._compact?{vb:"0 0 400 680",S:{cx:200,cy:100,r:44,labelY:154},I:{cx:200,cy:232,r:20},B:{cx:100,cy:360,r:44,labelY:414},G:{cx:300,cy:360,r:44,labelY:414},H:{cx:200,cy:540,r:48,labelY:598},E:{cx:84,cy:555,r:34,labelY:598},paths:{solar:"M200,144 L200,212",battery:"M188,242 C155,278 120,315 100,316",grid:"M212,242 C245,278 280,315 300,316",home:"M200,252 C200,390 200,460 200,492",ev:"M200,252 C200,400 140,490 84,521"},sunArc:"M30,68 Q200,6 370,68",sunX:200,sunY:20,sunR:12,sunRisingX:40,sunSettingX:360,sunLabelY:76,starX:[60,120,280,330,180],starY:[20,12,18,24,8],font:{label:11,value:15,sub:10},statusY:660,wmX:390,wmY:676}:{vb:"0 0 700 510",S:{cx:85,cy:140,r:48,labelY:200},I:{cx:220,cy:200,r:20},E:{cx:150,cy:390,r:42,labelY:442},B:{cx:340,cy:390,r:48,labelY:448},H:{cx:400,cy:230,r:52,labelY:292},G:{cx:570,cy:140,r:46,labelY:198},paths:{solar:"M118,148 C158,165 192,188 208,200",home:"M242,198 C300,200 350,210 360,218",battery:"M228,215 C260,280 320,340 338,342",grid:"M232,188 C320,130 450,110 524,130",ev:"M210,215 C180,275 162,330 150,348"},sunArc:"M20,52 Q330,2 640,52",sunX:330,sunY:12,sunR:12,sunRisingX:28,sunSettingX:632,sunLabelY:60,starX:[100,200,450,550,330],starY:[20,12,15,28,8],font:{label:11,value:16,sub:10},statusY:495,wmX:690,wmY:506}}_deviceIcon(e,t){const i=(t||"").toLowerCase();return"ev_charger"===(e||"").toLowerCase()||i.includes("keba")||i.includes("charger")||i.includes("wallbox")?j`<rect x="-5" y="-9" width="10" height="14" rx="2"/>
                       <path d="M-1.5,-3.5 L0,1.5 L1.5,-3.5"/>
                       <line x1="0" y1="5" x2="0" y2="9"/>`:i.includes("heiz")||i.includes("heat")||i.includes("warm")||i.includes("boiler")?j`<path d="M-3,-9 C-3,-3 3,-3 3,-9"/>
                       <path d="M-3,-2 C-3,4 3,4 3,-2"/>
                       <path d="M-3,5 C-3,9 3,9 3,5"/>`:i.includes("wash")||i.includes("spül")||i.includes("geschirr")||i.includes("wasch")?j`<circle r="9"/><circle r="4.5"/><circle r="1.3" fill="currentColor" opacity="0.3" stroke="none"/>`:i.includes("pool")||i.includes("pump")?j`<circle r="7"/><path d="M-5,0 L5,0 M0,-5 L0,5" opacity="0.5"/>`:i.includes("klima")||i.includes("ac")||i.includes("cool")||i.includes("air")?j`<rect x="-9" y="-5" width="18" height="10" rx="2"/>
                       <path d="M-5,5 C-5,9 -2,9 -2,5" fill="none"/>
                       <path d="M2,5 C2,9 5,9 5,5" fill="none"/>`:i.includes("light")||i.includes("licht")||i.includes("lamp")?j`<path d="M-4,-9 C-7,-2 -2,3 -1.5,5 L1.5,5 C2,3 7,-2 4,-9 C2,-12 -2,-12 -4,-9Z"/>
                       <line x1="-1.5" y1="6" x2="1.5" y2="6"/>`:j`<path d="M-2.5,-9 L-2.5,0 L-5,0 L0,9 L0,0 L2.5,0 L-2.5,-9Z"/>`}getCardSize(){return 7}static getStubConfig(){return{entity_prefix:"sensor.sem_"}}},{type:"sem-system-diagram-card",name:"SEM System Diagram",description:"Power flow visualization with inline SVG illustrations for each energy component"});const Ct=["/local/custom_components/solar_energy_management/dashboard/card/vendor/chart.umd.min.js","https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"],zt=["/local/custom_components/solar_energy_management/dashboard/card/vendor/chartjs-adapter-date-fns.bundle.min.js","https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js"];function Mt(e,t,i){if(!e.length)return void i(new Error("all sources failed"));const s=document.createElement("script");s.src=e[0],s.onload=()=>t(),s.onerror=()=>Mt(e.slice(1),t,i),document.head.appendChild(s)}let Et=null;const Dt=pe||{solar:"#ff9800",gridImport:"#488fc2",gridExport:"#8353d1",batteryOut:"#4db6ac",home:"#5BC8D8",ev:"#8DC892"},Ft={costs:{title:"energy_costs",y_label:"_currency_",stacked:!1,daily:[{suffix:"daily_costs",name:"Import",color:Dt.gridImport,type:"bar",negate:!0},{suffix:"daily_export_revenue",name:"export",color:Dt.gridExport,type:"bar"},{suffix:"daily_net_cost",name:"net",color:Dt.solar,type:"line",negate:!0}],monthly:[{suffix:"monthly_costs",name:"Import",color:Dt.gridImport,type:"bar",negate:!0},{suffix:"monthly_export_revenue",name:"export",color:Dt.gridExport,type:"bar"},{suffix:"monthly_net_cost",name:"net",color:Dt.solar,type:"line",negate:!0}]},savings:{title:"energy_savings",y_label:"_currency_",stacked:!0,daily:[{suffix:"daily_savings",name:"solar_savings",color:Dt.solar,type:"area"},{suffix:"daily_battery_savings",name:"battery_savings",color:Dt.batteryOut,type:"area"}],monthly:[{suffix:"monthly_savings",name:"solar_savings",color:Dt.solar,type:"area"},{suffix:"monthly_battery_savings",name:"battery_savings",color:Dt.batteryOut,type:"area"}]},energy:{title:"energy_balance",y_label:"kWh",stacked:!1,defaultPeriod:"7d",daily:[{suffix:"daily_solar_energy",name:"solar",color:Dt.solar,type:"bar"},{suffix:"daily_home_energy",name:"home",color:Dt.home,type:"bar"},{suffix:"daily_grid_import_energy",name:"grid_import",color:Dt.gridImport,type:"bar"},{suffix:"daily_grid_export_energy",name:"grid_export",color:Dt.gridExport,type:"bar"}],monthly:[{suffix:"monthly_solar_energy",name:"solar",color:Dt.solar,type:"bar"},{suffix:"monthly_home_energy",name:"home",color:Dt.home,type:"bar"},{suffix:"monthly_grid_import_energy",name:"grid_import",color:Dt.gridImport,type:"bar"},{suffix:"monthly_grid_export_energy",name:"grid_export",color:Dt.gridExport,type:"bar"}]},power:{title:"power_flow",y_label:"W",stacked:!1,hourly:[{suffix:"solar_power",name:"solar",color:Dt.solar,type:"area"},{suffix:"home_consumption_power",name:"home",color:Dt.home,type:"area"},{suffix:"grid_power",name:"grid",color:Dt.gridImport,type:"area"}]},forecast:{title:"forecast_vs_actual",y_label:"W",stacked:!1,hourly:[{suffix:"forecast_power_now_w",name:"forecast",color:Dt.solar,type:"area"},{suffix:"solar_power",name:"actual",color:Dt.batteryOut,type:"line"}]},battery:{title:"battery",y_label:"W",y2_label:"%",stacked:!1,hourly:[{suffix:"battery_power",name:"power",color:Dt.batteryOut,type:"area"},{suffix:"battery_soc",name:"soc",color:"#ff9800",type:"line",y_axis:1}]},ev:{title:"ev_charging",y_label:"W",stacked:!0,defaultPeriod:"today",y_min:0,y_suggested_max:2e3,hourly:[{suffix:"flow_solar_to_ev_power",name:"solar",color:Dt.solar,type:"area"},{suffix:"flow_battery_to_ev_power",name:"battery",color:Dt.batteryOut,type:"area"},{suffix:"flow_grid_to_ev_power",name:"grid",color:Dt.gridImport,type:"area"}],daily:[{suffix:"daily_ev_energy",name:"ev_energy",color:Dt.ev,type:"bar"}],monthly:[{suffix:"monthly_ev_energy",name:"ev_energy",color:Dt.ev,type:"bar"}]}};$e("sem-chart-card",class extends ke{constructor(){super(),this._chart=null,this._period=null,this._fetchTimer=null,this._cachedChartTheme=null,this._boundPeriodHandler=e=>this._onPeriodChange(e.detail),this._prefix="sensor.sem_",this._preset=null,this._emptyMsg=""}setConfig(e){if(!e.preset&&!e.series)throw new Error("sem-chart-card requires either preset or series config");this._config=e,this._prefix=e.entity_prefix||"sensor.sem_",this._preset=e.preset?Ft[e.preset]:null,this.requestUpdate()}set hass(e){this._hass=e;const t=e?.language;if(t!==this._lang)return this._lang=t,void this.requestUpdate();this._period||this._setDefaultPeriod()}get hass(){return this._hass}connectedCallback(){super.connectedCallback(),document.addEventListener("sem-period-change",this._boundPeriodHandler),this._rollInterval=setInterval(()=>this._rollRelativePeriod(),3e5),this._boundVisibility=()=>{document.hidden||this._rollRelativePeriod()},document.addEventListener("visibilitychange",this._boundVisibility)}disconnectedCallback(){super.disconnectedCallback(),document.removeEventListener("sem-period-change",this._boundPeriodHandler),this._boundVisibility&&document.removeEventListener("visibilitychange",this._boundVisibility),clearInterval(this._rollInterval),this._chart&&(this._chart.destroy(),this._chart=null),clearTimeout(this._fetchTimer)}_rollRelativePeriod(){if(!this._period||!this._hass)return;const e=this._config?.default_period||this._preset?.defaultPeriod,t="24h"===e?"24h":"7d"===e?"7d":"today"===e?"today":"week";this._period.key===t&&this._setDefaultPeriod()}firstUpdated(){this._period||this._setDefaultPeriod()}static get styles(){return[we,a`
            :host { display: block; }
            .sem-chart-wrap {
                padding: 16px;
                min-height: 280px;
                position: relative;
            }
            .chart-header { margin-bottom: 12px; }
            .chart-title {
                font-size: 15px; font-weight: 600;
                color: var(--primary-text-color, #e0e0e0);
                font-family: 'Segoe UI','Roboto',sans-serif;
                letter-spacing: 0.3px;
                font-variant-numeric: tabular-nums;
            }
            .chart-subtitle {
                font-size: 12px;
                color: var(--secondary-text-color, #757575);
                margin-top: 2px;
                font-family: 'Segoe UI','Roboto',sans-serif;
                font-variant-numeric: tabular-nums;
            }
            .chart-container {
                position: relative;
                height: 250px;
                filter: drop-shadow(0 0 1px rgba(200,220,240,0.10));
            }
            canvas { width: 100% !important; height: 100% !important; }
            .empty-msg {
                position: absolute;
                inset: 0;
                display: none;
                align-items: center;
                justify-content: center;
                color: var(--secondary-text-color, #616161);
                font-size: 13px;
                font-family: 'Segoe UI','Roboto',sans-serif;
            }
            .empty-msg.visible { display: flex; }
        `]}render(){const e=this._preset||{},t=this._config?.title?this._t(this._config.title):this._t(e.title||"SEM Chart"),i=this._period?.labelKey?this._t(this._period.labelKey):"";return W`
            <ha-card>
                <div class="sem-chart-wrap">
                    <div class="chart-header">
                        <div class="chart-title">${t}</div>
                        <div class="chart-subtitle">${i}</div>
                    </div>
                    <div class="chart-container">
                        <canvas style="display:${this._emptyMsg?"none":"block"}"></canvas>
                        <div class="empty-msg ${this._emptyMsg?"visible":""}">${this._emptyMsg}</div>
                    </div>
                </div>
            </ha-card>
        `}_startOfDayInHaTz(e){return function(e,t){if(!t)return new Date(e.getFullYear(),e.getMonth(),e.getDate());try{const i=new Intl.DateTimeFormat("en-US",{timeZone:t,year:"numeric",month:"2-digit",day:"2-digit"}),s=Object.fromEntries(i.formatToParts(e).map(e=>[e.type,e.value])),r=new Date(Number(s.year),Number(s.month)-1,Number(s.day),0,0,0,0),a=new Intl.DateTimeFormat("en-US",{timeZone:t,hour:"2-digit",minute:"2-digit",hour12:!1}).formatToParts(r),o=Number(a.find(e=>"hour"===e.type).value),n=Number(a.find(e=>"minute"===e.type).value),l=(60*o+n)%1440,c=0===l?0:l<=720?-l:1440-l;return new Date(r.getTime()+60*c*1e3)}catch(t){return new Date(e.getFullYear(),e.getMonth(),e.getDate())}}(e,this._hass?.config?.time_zone)}_setDefaultPeriod(){const e=new Date,t=this._preset,i=this._config?.default_period||t&&t.defaultPeriod,s="today"===i;if(t&&(s||"24h"===i||t.hourly&&!t.daily)){const t=s?this._startOfDayInHaTz(e):new Date(e.getTime()-864e5),i=s?"period_today":"last_24h",r=s?"today":"24h";this._onPeriodChange({start:t,end:e,granularity:"hour",labelKey:i,key:r})}else if("7d"===i){const t=this._startOfDayInHaTz(e);t.setDate(t.getDate()-6),this._onPeriodChange({start:t,end:e,granularity:"day",labelKey:"last_7_days",key:"7d"})}else{const t=e.getDay()||7,i=this._startOfDayInHaTz(e);i.setDate(i.getDate()-(t-1)),this._onPeriodChange({start:i,end:e,granularity:"day",labelKey:"period_this_week",key:"week"})}}_onPeriodChange(e){this._period={...e,labelKey:e.labelKey||{today:"period_today",yesterday:"period_yesterday",week:"period_this_week",month:"period_this_month",year:"period_this_year","24h":"last_24h","7d":"last_7_days"}[e.key]},this.requestUpdate(),clearTimeout(this._fetchTimer),this._fetchTimer=setTimeout(()=>this._fetchAndRender(),150)}_resolveSeries(){if(this._config?.series)return this._config.series.map(e=>({entity:e.entity,name:e.name||e.entity,color:e.color||"#42A5F5",type:e.type||"bar",y_axis:e.y_axis||0}));const e=this._preset;if(!e)return[];const t=this._period?.granularity||"day";if(this._config?.per_charger&&"ev"===this._config?.preset&&"hour"===t)return this._discoverPerChargerSeries();return("hour"===t&&e.hourly?e.hourly:"month"===t&&e.monthly?e.monthly:e.daily||e.hourly||[]).map(e=>({entity:`${this._prefix}${e.suffix}`,name:this._t(e.name),color:e.color,type:e.type,y_axis:e.y_axis||0,negate:e.negate||!1}))}_discoverPerChargerSeries(){const e=this._hass?.states||{},t=["#8DC892","#64B5F6","#FFB74D","#BA68C8","#4DB6AC","#F06292","#A1887F","#7986CB"],i=/^sensor\.sem_charger_(.+)_power$/,s=[];for(const t of Object.keys(e)){const r=t.match(i);if(!r)continue;const a=r[1],o=e[t]?.attributes?.friendly_name?.replace(/^SEM\s+/i,"").replace(/\s+Power$/i,"")||a.replace(/_/g," ");s.push({id:a,eid:t,friendly:o})}return s.sort((e,t)=>e.id.localeCompare(t.id)),s.map((e,i)=>({entity:e.eid,name:e.friendly,color:t[i%t.length],type:"area",y_axis:0}))}async _fetchAndRender(){if(!this._hass||!this._period)return;const e=this._resolveSeries();if(!e.length)return;const{start:t,end:i,granularity:s}=this._period;let r;try{r=await this._fetchStatistics(e,t.toISOString(),i.toISOString(),s)}catch(e){return console.debug("sem-chart-card: fetch error",e),void this._showEmpty(this._t("data_unavailable"))}r&&!r.every(e=>!e.data.length)?(this._hideEmpty(),await this.updateComplete,await this._renderChart(r,e)):this._showEmpty(this._t("no_data_for_period"))}async _fetchStatistics(e,t,i,s){const r=e.map(e=>e.entity),a="month"===s?"month":"hour"===s?"hour":"day";let o;try{o=await this._hass.callWS({type:"recorder/statistics_during_period",start_time:t,end_time:i,statistic_ids:r,period:a,types:["state","mean","max"]})}catch{o=await this._hass.callWS({type:"history/statistics_during_period",start_time:t,end_time:i,statistic_ids:r,period:a})}const n=(this._config?.stacked??this._preset?.stacked??!1)&&"hour"===a;return e.map(e=>({data:(o[e.entity]||[]).map(t=>{let i=n?t.mean??t.state??0:t.max??t.state??t.mean??0;return e.negate&&(i=-i),{x:new Date(t.start),y:i}})}))}async _renderChart(e,t){const i=await(Et||(Et=new Promise((e,t)=>{window.Chart?e(window.Chart):Mt(Ct,()=>{Mt(zt,()=>e(window.Chart),()=>e(window.Chart))},()=>t(new Error("Failed to load Chart.js")))}),Et)),s=this.renderRoot.querySelector("canvas");if(!s)return;const r=this._theme(),a=this._preset||{},o=this._config?.stacked??a.stacked??!1;let n=this._config?.y_label||a.y_label||"";"_currency_"===n&&(n=me(this._hass));const l=a.y2_label||"",c=t.some(e=>1===e.y_axis),d=this._period?.granularity||"day",p=s.getContext("2d"),h=t.map((t,i)=>{const s="area"===t.type,r="bar"===t.type;return{label:t.name,data:e[i].data,backgroundColor:r?t.color+"CC":s?t.color+"30":"transparent",borderColor:t.color,borderWidth:r?0:2,fill:!!s&&(o&&i>0?"-1":"origin"),type:r?"bar":"line",tension:.4,pointRadius:0,pointHitRadius:10,pointHoverRadius:4,pointHoverBorderWidth:2,pointHoverBackgroundColor:t.color,pointHoverBorderColor:"#fff",yAxisID:1===t.y_axis?"y1":"y",order:r?2:1,borderRadius:r?4:0,barPercentage:.7}}),_="hour"===d?"hour":"month"===d?"month":"day",g={id:"crosshair",afterDraw(e){if(e.tooltip?._active?.length){const t=e.tooltip._active[0].element.x,i=e.scales.y,s=e.ctx;s.save(),s.beginPath(),s.moveTo(t,i.top),s.lineTo(t,i.bottom),s.lineWidth=1,s.strokeStyle="rgba(255,255,255,0.15)",s.stroke(),s.restore()}}},u={type:"bar",data:{datasets:h},plugins:[g,{id:"gradientFill",beforeDatasetsDraw(e){const i=e.ctx;e.data.datasets.forEach((s,r)=>{if("area"!==t[r]?.type)return;if(e.getDatasetMeta(r).hidden)return;const a=e.scales[s.yAxisID||"y"];if(!a)return;const o=i.createLinearGradient(0,a.top,0,a.bottom);o.addColorStop(0,s.borderColor+"60"),o.addColorStop(.6,s.borderColor+"18"),o.addColorStop(1,s.borderColor+"02"),s.backgroundColor=o})}}],options:{responsive:!0,maintainAspectRatio:!1,animation:{duration:300,easing:"easeOutQuart"},interaction:{mode:"index",intersect:!1},plugins:{legend:{display:!0,position:"bottom",labels:{color:r.textSec||"#9e9e9e",font:{size:11,weight:"500",family:"'Segoe UI','Roboto',sans-serif"},boxWidth:12,boxHeight:12,borderRadius:3,useBorderRadius:!0,padding:14,generateLabels:e=>function(e,t,i){return e.map(e=>{const s=t[e.datasetIndex];if(!s)return e;const r=s.data[s.data.length-1],a=r?.y??0,o="y1"===s.yAxisID?"%":i||"",n=Math.abs(a),l=n>=1e3?(a/1e3).toFixed(1)+"k":n<10?a.toFixed(1):a.toFixed(0);return e.text=`${e.text}: ${l} ${o}`,e})}(i.defaults.plugins.legend.labels.generateLabels(e),e.data.datasets,n)}},tooltip:{backgroundColor:r.tooltipBg||"rgba(15,18,25,0.94)",titleColor:r.tooltipText||"#e0e0e0",titleFont:{family:"'Segoe UI','Roboto',sans-serif",weight:"600",size:12},bodyColor:r.textSec||"#b0b0b0",bodyFont:{family:"'Segoe UI','Roboto',sans-serif",size:11},borderColor:r.tooltipBorder||"rgba(255,255,255,0.08)",borderWidth:1,cornerRadius:10,padding:{top:10,bottom:10,left:14,right:14},bodySpacing:6,displayColors:!0,boxPadding:4,callbacks:{title:e=>{if(!e||!e.length)return"";const t=new Date(e[0].parsed.x);if(isNaN(t))return"";const i=this._hass?.language||"en",s=this._hass?.config?.time_zone||void 0;try{return"hour"===d?t.toLocaleTimeString(i,{hour:"2-digit",minute:"2-digit",timeZone:s}):"month"===d?t.toLocaleDateString(i,{month:"short",year:"numeric",timeZone:s}):t.toLocaleDateString(i,{day:"numeric",month:"short",timeZone:s})}catch(e){return"hour"===d?t.toLocaleTimeString(i):t.toLocaleDateString(i)}},label:e=>{const t=e.parsed.y,i="y1"===e.dataset.yAxisID?"%":n,s=Math.abs(t),r=s>=1e3?(t/1e3).toFixed(1)+"k":s<10?t.toFixed(2):t.toFixed(1);return` ${e.dataset.label}: ${r} ${i}`}}}},scales:{x:{type:"time",min:this._period.start.toISOString(),max:this._period.end.toISOString(),time:{unit:_,tooltipFormat:"hour"===d?"HH:mm":"month"===d?"MMM yyyy":"dd MMM",displayFormats:{hour:"HH:mm",day:"dd MMM",month:"MMM"}},grid:{color:"rgba(255,255,255,0.02)",drawBorder:!1,drawTicks:!1},ticks:{color:r.textSec||"#757575",font:{size:10,family:"'Segoe UI','Roboto',sans-serif"},maxRotation:0,padding:6,callback:(e,t,i)=>{const s=i[t];if(!s)return e;const r=new Date(s.value);if(isNaN(r))return e;const a=this._hass?.language||"en",o=this._hass?.config?.time_zone||void 0;try{return"hour"===_?r.toLocaleTimeString(a,{hour:"2-digit",minute:"2-digit",timeZone:o}):"month"===_?r.toLocaleDateString(a,{month:"short",timeZone:o}):r.toLocaleDateString(a,{day:"numeric",month:"short",timeZone:o})}catch(e){return"hour"===_?r.toLocaleTimeString(a,{hour:"2-digit",minute:"2-digit"}):r.toLocaleDateString(a,{day:"numeric",month:"short"})}}},stacked:o},y:{position:"left",grid:{color:"rgba(255,255,255,0.04)",drawBorder:!1,drawTicks:!1},ticks:{color:r.textSec||"#757575",font:{size:10,family:"'Segoe UI','Roboto',sans-serif"},padding:8,callback:e=>{const t=Math.abs(e);return t>=1e3?(e/1e3).toFixed(1)+"k":t<.01&&t>0?"":e%1==0?e:e.toFixed(1)}},title:{display:!!n,text:n,color:r.textSec||"#757575",font:{size:11,family:"'Segoe UI','Roboto',sans-serif"}},stacked:o,beginAtZero:"W"!==n||0===this._preset?.y_min,...null!=this._preset?.y_min?{min:this._preset.y_min}:{},...null!=this._preset?.y_suggested_max?{suggestedMax:this._preset.y_suggested_max}:{}}}}};c&&(u.options.scales.y1={position:"right",grid:{drawOnChartArea:!1,drawTicks:!1},ticks:{color:"#ff9800",font:{size:10},padding:8,callback:e=>e+"%"},title:{display:!!l,text:l,color:"#ff9800",font:{size:11}},min:0,max:100}),this._chart&&(this._chart.destroy(),this._chart=null),this._chart=new i(p,u)}_showEmpty(e){this._emptyMsg=e,this.requestUpdate()}_hideEmpty(){this._emptyMsg&&(this._emptyMsg="",this.requestUpdate())}getCardSize(){return 5}static getStubConfig(){return{preset:"costs"}}},{type:"sem-chart-card",name:"SEM Chart",description:"Period-reactive chart with glassmorphism styling and built-in presets"});const{I:It}=oe,Bt=e=>e,Nt=()=>document.createComment(""),At=(e,t,i)=>{const s=e._$AA.parentNode,r=void 0===t?e._$AB:t._$AA;if(void 0===i){const t=s.insertBefore(Nt(),r),a=s.insertBefore(Nt(),r);i=new It(t,a,e,e.options)}else{const t=i._$AB.nextSibling,a=i._$AM,o=a!==e;if(o){let t;i._$AQ?.(e),i._$AM=e,void 0!==i._$AP&&(t=e._$AU)!==a._$AU&&i._$AP(t)}if(t!==r||o){let e=i._$AA;for(;e!==t;){const t=Bt(e).nextSibling;Bt(s).insertBefore(e,r),e=t}}}return i},Tt=(e,t,i=e)=>(e._$AI(t,i),e),Pt={},Rt=(e,t=Pt)=>e._$AH=t,Lt=e=>{e._$AR(),e._$AA.remove()},Ot=(e,t,i)=>{const s=new Map;for(let r=t;r<=i;r++)s.set(e[r],r);return s},Ut=yt(class extends vt{constructor(e){if(super(e),e.type!==mt)throw Error("repeat() can only be used in text expressions")}dt(e,t,i){let s;void 0===i?i=t:void 0!==t&&(s=t);const r=[],a=[];let o=0;for(const t of e)r[o]=s?s(t,o):o,a[o]=i(t,o),o++;return{values:a,keys:r}}render(e,t,i){return this.dt(e,t,i).values}update(e,[t,i,s]){const r=(e=>e._$AH)(e),{values:a,keys:o}=this.dt(t,i,s);if(!Array.isArray(r))return this.ut=o,a;const n=this.ut??=[],l=[];let c,d,p=0,h=r.length-1,_=0,g=a.length-1;for(;p<=h&&_<=g;)if(null===r[p])p++;else if(null===r[h])h--;else if(n[p]===o[_])l[_]=Tt(r[p],a[_]),p++,_++;else if(n[h]===o[g])l[g]=Tt(r[h],a[g]),h--,g--;else if(n[p]===o[g])l[g]=Tt(r[p],a[g]),At(e,l[g+1],r[p]),p++,g--;else if(n[h]===o[_])l[_]=Tt(r[h],a[_]),At(e,r[p],r[h]),h--,_++;else if(void 0===c&&(c=Ot(o,_,g),d=Ot(n,p,h)),c.has(n[p]))if(c.has(n[h])){const t=d.get(o[_]),i=void 0!==t?r[t]:null;if(null===i){const t=At(e,r[p]);Tt(t,a[_]),l[_]=t}else l[_]=Tt(i,a[_]),At(e,r[p],i),r[t]=null;_++}else Lt(r[h]),h--;else Lt(r[p]),p++;for(;_<=g;){const t=At(e,l[g+1]);Tt(t,a[_]),l[_++]=t}for(;p<=h;){const e=r[p++];null!==e&&Lt(e)}return this.ut=o,Rt(e,l),G}});function Ht(e){const t=[],i=new Set,s=r=>{var a;i.has(r.id)||(t.push(r),i.add(r.id),(a=r.id,e.filter(e=>(e.dependsOn||[]).includes(a)&&!i.has(e.id))).forEach(s))};return e.filter(e=>!(e.dependsOn||[]).length).forEach(s),e.forEach(e=>{i.has(e.id)||t.push(e)}),t}const Wt=["switch","current","input_boolean","service"],jt={switch:["switch"],current:["number","input_number"],input_boolean:["input_boolean"]};function Gt(e){return String(e??"").replace(/&/g,"&amp;").replace(/"/g,"&quot;").replace(/</g,"&lt;").replace(/>/g,"&gt;")}const qt="width:100%;padding:8px;margin:6px 0 12px;border-radius:6px;border:1px solid rgba(255,255,255,0.1);background:rgba(0,0,0,0.2);color:inherit;box-sizing:border-box";$e("sem-load-priority-card",class extends ke{constructor(){super(),this.devices=[],this.targetPeakLimit=5,this.currentPeak=0,this.loadManagementStatus="normal",this._sortable=null,this._interacting=!1,this._lastDeviceSig="",this._showHelp=!1,this._goalOpen={},this._goalDrag=null}setConfig(e){this._config=e,this.entityPrefix=e.entity_prefix||"sensor.sem_",this.requestUpdate()}set hass(e){this._hass,this._hass=e;const t=e?.language;if(t!==this._lang)return this._lang=t,this._lastDeviceSig="",void this.requestUpdate();if(this._interacting)return;if(this._isFrozen())return;if(this._priorityFrozenUntil&&Date.now()<this._priorityFrozenUntil)return;const i=e?.states[`${this.entityPrefix}controllable_devices_count`],s=e?.states[`${this.entityPrefix}consecutive_peak_15min`],r=e?.states[`${this.entityPrefix}load_management_status`],a=(i?.state||"")+"|"+(s?.state||"")+"|"+(r?.state||"");a!==this._lastKey&&(this._lastKey=a,this._updateDeviceData(),this.requestUpdate())}get hass(){return this._hass}disconnectedCallback(){super.disconnectedCallback(),this._drag&&(window.removeEventListener("pointermove",this._dragMoveBound),window.removeEventListener("pointerup",this._dragEndBound),window.removeEventListener("pointercancel",this._dragEndBound),this._drag=null,this._interacting=!1)}async firstUpdated(){this._bindEvents()}async updated(e){const t=this.devices.map(e=>e.id).join(",");t!==this._lastDeviceSig&&(this._lastDeviceSig=t,this._bindEvents())}static get styles(){return a`
            :host { display: block; }
            ha-card {
                overflow: visible;
                backdrop-filter: blur(18px) saturate(160%);
                -webkit-backdrop-filter: blur(18px) saturate(160%);
                border: 1px solid var(--divider-color, rgba(255,255,255,0.08));
                border-radius: 16px !important;
                box-shadow: var(--ha-card-box-shadow, 0 4px 24px rgba(0,0,0,0.35));
            }
            .card-content { padding: 14px 16px; font-family: 'Segoe UI','Roboto',sans-serif; color: var(--primary-text-color); }
            .status-bar { display:flex; align-items:center; gap:8px; margin-bottom:12px; padding-bottom:10px; border-bottom:1px solid var(--divider-color, rgba(128,128,128,0.12)); font-size:0.95em; }
            .status-text { text-transform:uppercase; letter-spacing:0.5px; font-weight:600; opacity:0.85; }
            .peak-dot { width:9px; height:9px; border-radius:50%; }
            .peak-box { background:var(--secondary-background-color, rgba(255,255,255,0.04)); border:1px solid var(--divider-color, rgba(255,255,255,0.08)); border-radius:12px; padding:12px; margin-bottom:10px; backdrop-filter: blur(8px); }
            .peak-row { display:flex; justify-content:space-between; margin-bottom:4px; font-size:1em; }
            .peak-row:last-of-type { margin-bottom:0; }
            .dim { opacity:0.55; font-size:1em; }
            .mono { font-variant-numeric:tabular-nums; font-weight:500; }
            .bar { width:100%; height:5px; background:var(--divider-color, rgba(128,128,128,0.12)); border-radius:3px; overflow:hidden; margin-top:8px; }
            .bar-fill { height:100%; border-radius:3px; transition:width 0.4s ease, background 0.4s ease; }
            .target-row { display:flex; align-items:center; gap:8px; margin-top:6px; }
            .target-row input { width:70px; padding:5px 8px; border:1px solid var(--divider-color, rgba(255,255,255,0.08)); border-radius:8px; background:var(--card-background-color, rgba(0,0,0,0.2)); color:var(--primary-text-color); text-align:center; font-size:1em; }
            .target-row input:focus { outline:none; border-color:#ff9800; }
            .target-row button { padding:5px 14px; border:none; border-radius:8px; background:#ff9800; color:#fff; cursor:pointer; font-size:0.95em; }
            .target-row button:hover { background:#e68900; }
            .section-label { font-size:0.95em; opacity:0.55; margin-bottom:10px; display:flex; align-items:center; gap:6px; }
            .device-list { min-height:40px; }
            .device { display:flex; align-items:stretch; background:var(--secondary-background-color, rgba(255,255,255,0.04)); border:1px solid var(--divider-color, rgba(255,255,255,0.08)); border-radius:12px; margin-bottom:6px; transition:transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease; overflow:hidden; backdrop-filter:blur(8px); }
            /* Pointer-drag (Lit-native): the lifted row follows the finger,
               a bright line shows where it will drop. box-shadow is not
               clipped by the row's overflow, so the drop-line always shows. */
            .device.dragging-row { opacity:0.95; z-index:20; position:relative; border-color:#ff9800; box-shadow:0 10px 26px rgba(0,0,0,0.45); cursor:grabbing; }
            .device.drop-above { box-shadow:0 -3px 0 0 #ff9800; }
            .device.drop-below { box-shadow:0 3px 0 0 #ff9800; }
            .drag-handle { display:flex; align-items:center; justify-content:center; width:32px; min-width:32px; cursor:grab; font-size:16px; opacity:0.3; user-select:none; touch-action:none; border-right:1px solid var(--divider-color, rgba(128,128,128,0.12)); }
            .drag-handle:hover { opacity:0.6; }
            .drag-handle:active { cursor:grabbing; }
            .device-body { flex:1; padding:10px 12px; min-width:0; }
            .device-top { display:flex; justify-content:space-between; align-items:center; margin-bottom:6px; }
            .device-name { display:flex; align-items:center; gap:6px; font-weight:500; font-size:0.95em; min-width:0; overflow:hidden; }
            .device-name span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
            .device-power { font-size:1em; font-weight:500; font-variant-numeric:tabular-nums; white-space:nowrap; opacity:0.7; }
            .device-bottom { display:flex; align-items:center; gap:8px; font-size:0.95em; flex-wrap:wrap; }
            .status-dot { width:7px; height:7px; border-radius:50%; background:var(--divider-color, rgba(128,128,128,0.12)); flex-shrink:0; }
            .status-dot.on { background:#4caf50; box-shadow:0 0 6px #4caf50; }
            .status-dot.shed { background:#f44336; box-shadow:0 0 6px #f44336; }
            .spacer { flex:1; }
            .badge { padding:2px 7px; border-radius:8px; font-size:0.95em; font-weight:600; }
            .badge.priority { background:#ff9800; color:#fff; min-width:14px; text-align:center; }
            .toggle-label { display:flex; align-items:center; gap:4px; }
            .arrows { display:flex; flex-direction:column; gap:1px; }
            .arrow-btn { border:none; background:none; cursor:pointer; font-size:11px; padding:0 4px; opacity:0.35; line-height:1; color:var(--primary-text-color,inherit); }
            .arrow-btn:hover { opacity:0.8; }
            .mode-select { background:var(--card-background-color,rgba(40,40,55,0.7)); color:var(--primary-text-color); border:1px solid var(--divider-color,rgba(255,255,255,0.08)); border-radius:6px; padding:2px 6px; font-size:13px; font-family:'Segoe UI','Roboto',sans-serif; cursor:pointer; -webkit-appearance:none; appearance:none; }
            .mode-select:focus { outline:none; border-color:rgba(255,152,0,0.5); }
            .configure-btn { display:inline-flex; align-items:center; gap:3px; padding:2px 6px; background:rgba(255,193,7,0.12); border:1px solid rgba(255,193,7,0.25); border-radius:5px; color:#ffc107; cursor:pointer; font-size:0.9em; }
            .configure-btn:hover { background:rgba(255,193,7,0.22); }
            .hint { text-align:center; font-size:0.95em; opacity:0.4; margin-top:10px; }
            .help-btn {
                width:24px; height:24px; border-radius:50%;
                border:1px solid var(--divider-color, rgba(255,255,255,0.2));
                background:transparent; color:var(--secondary-text-color,#999);
                font-weight:700; cursor:pointer; margin-left:8px; flex:0 0 auto;
            }
            .help-btn.active { color:#ff9800; border-color:#ff9800; }
            .help-panel {
                margin:4px 0 14px; padding:12px 14px; border-radius:10px;
                background:rgba(128,128,128,0.08);
                font-size:0.9em; line-height:1.5;
            }
            .help-item { margin-bottom:8px; }
            .help-item:last-child { margin-bottom:0; }
            .help-item b { color:var(--primary-text-color,#e0e0e0); }
            .goal-btn {
                width:26px; height:26px; border-radius:8px;
                border:1px solid var(--divider-color, rgba(255,255,255,0.15));
                background:transparent; color:var(--secondary-text-color,#999);
                cursor:pointer; display:flex; align-items:center; justify-content:center;
                margin-left:6px; flex:0 0 auto;
            }
            .goal-btn.active { color:#ff9800; border-color:#ff9800; }
            .goal-progress { display:flex; align-items:center; gap:8px; }
            .goal-bar {
                flex:1 1 auto; height:5px; border-radius:3px;
                background:rgba(128,128,128,0.2); overflow:hidden; max-width:220px;
            }
            .goal-bar-fill { height:100%; border-radius:3px; transition:width 0.4s; }
            .goal-progress-text { font-size:12px; color:var(--secondary-text-color,#999); white-space:nowrap; }
            .ge-spacer { margin-left:auto; }
            .ge-unit-select {
                appearance:none; -webkit-appearance:none;
                background-color:var(--secondary-background-color, rgba(255,255,255,0.07));
                background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath fill='%23bbbbbb' d='M7 10l5 5 5-5z'/%3E%3C/svg%3E");
                background-repeat:no-repeat; background-position:right 4px center;
                background-size:12px;
                color:var(--primary-text-color,#e0e0e0);
                border:1px solid var(--divider-color, rgba(255,255,255,0.12));
                border-radius:6px; padding:2px 20px 2px 8px;
                font-size:11px; font-weight:600; cursor:pointer;
                text-transform:none; letter-spacing:0;
            }
            .range-wrap { padding:6px 8px 10px; }
            .range-labels {
                display:flex; justify-content:space-between;
                font-size:12px; color:var(--primary-text-color,#e0e0e0);
                margin-bottom:10px;
            }
            .range-labels b { font-variant-numeric:tabular-nums; }
            .range-track {
                position:relative; height:6px; border-radius:3px;
                background:rgba(255,255,255,0.14); margin:6px 9px;
                touch-action:none; cursor:pointer;
            }
            .range-fill {
                position:absolute; top:0; height:100%; border-radius:3px;
                background:linear-gradient(90deg, #8DC892, #ff9800);
            }
            .range-handle {
                position:absolute; top:50%; width:18px; height:18px;
                border-radius:50%; transform:translate(-50%, -50%);
                background:#fff; box-shadow:0 1px 3px rgba(0,0,0,0.5);
                cursor:grab; touch-action:none; pointer-events:none;
            }
            .range-handle-min { border:3px solid #8DC892; }
            .range-handle-max { border:3px solid #ff9800; }
            /* EV charge-target look (#559 UI merge) */
            .goal-editor {
                margin:8px 0 4px 28px; padding:10px 12px;
                border:1px solid var(--divider-color, rgba(255,255,255,0.12));
                border-radius:10px; background:rgba(255,255,255,0.025);
            }
            .ge-title {
                font-size:11px; text-transform:uppercase; letter-spacing:0.05em;
                color:var(--secondary-text-color,#999);
                display:flex; align-items:center; gap:5px; margin-bottom:4px;
            }
            .ge-row {
                display:flex; align-items:center; min-height:34px; padding:2px 0;
            }
            .ge-row + .ge-row { border-top:1px solid rgba(255,255,255,0.06); }
            .ge-label { font-size:12px; color:var(--primary-text-color,#e0e0e0); }
            .ge-ctl { margin-left:auto; display:flex; align-items:center; gap:7px; }
            .ge-unit { font-size:12px; color:var(--secondary-text-color,#999); }
            .ge-mode-select {
                appearance:none; -webkit-appearance:none;
                background-color:var(--secondary-background-color, rgba(255,255,255,0.07));
                background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath fill='%23bbbbbb' d='M7 10l5 5 5-5z'/%3E%3C/svg%3E");
                background-repeat:no-repeat; background-position:right 6px center;
                background-size:14px;
                color:var(--primary-text-color,#e0e0e0);
                border:1px solid var(--divider-color, rgba(255,255,255,0.12));
                border-radius:8px; padding:4px 24px 4px 10px;
                font-size:12px; font-weight:600; cursor:pointer;
            }
            .goal-editor input[type=number], .goal-editor input[type=time], .goal-editor input[type=text] {
                background:var(--secondary-background-color, rgba(255,255,255,0.07));
                border:1px solid var(--divider-color, rgba(255,255,255,0.12));
                border-radius:8px; color:var(--primary-text-color,#e0e0e0);
                padding:4px 8px; width:72px; font-size:12px;
                font-variant-numeric:tabular-nums;
            }
            .goal-editor input.ge-entity { width:160px; max-width:100%; }
            /* Mobile: the stop-when row (entity + ≥ + number) overflows a
               phone width and squeezes the label onto two lines. Stack the
               label above the control and let the entity field flex. */
            @media (max-width: 480px) {
                .goal-editor { margin-left:6px; padding:10px; }
                .ge-row { flex-wrap:wrap; align-items:flex-start; }
                .ge-label { flex:1 0 100%; margin-bottom:4px; }
                .ge-ctl { margin-left:0; width:100%; }
                .goal-editor input.ge-entity { flex:1; width:auto; }
            }
            .ge-hint {
                display:flex; align-items:center; gap:6px;
                font-size:12px; color:var(--secondary-text-color,#999); padding:4px 0 6px;
            }
            /* (#620) battery-overnight toggle switch */
            .batt-toggle {
                width:34px; height:19px; border-radius:11px; border:none; padding:0;
                position:relative; cursor:pointer; background:rgba(255,255,255,0.15);
                transition:background .2s;
            }
            .batt-toggle.on { background:#4db6ac; }
            .batt-toggle .knob {
                position:absolute; top:2px; left:2px; width:15px; height:15px;
                border-radius:50%; background:#fff; transition:left .2s;
            }
            .batt-toggle.on .knob { left:17px; }
            .empty { text-align:center; padding:20px 0; opacity:0.4; font-size:1em; }
        `}_updateDeviceData(){if(!this._hass)return;const e=this._hass.states[`${this.entityPrefix}target_peak_limit`],t=this._hass.states[`${this.entityPrefix}consecutive_peak_15min`],i=this._hass.states[`${this.entityPrefix}load_management_status`],s=this._hass.states[`${this.entityPrefix}controllable_devices_count`];e&&(this.targetPeakLimit=parseFloat(e.state)||5),t&&(this.currentPeak=parseFloat(t.state)||0),i&&(this.loadManagementStatus=i.state||"normal"),s?.attributes?.devices&&(this.devices=Object.entries(s.attributes.devices).map(([e,t])=>({id:e,name:t.name||e.replace(/^(load_device_|energy_dashboard_)/,"").replace(/_/g," "),power:(t.current_power||0)/1e3,rating:t.power_rating||0,priority:t.priority||5,isOn:t.is_on||!1,isShed:t.is_shed||!1,shedReason:t.shed_reason||null,isControllable:!1!==t.is_controllable,isCritical:t.is_critical||!1,deviceType:t.device_type||"unknown",isAvailable:t.is_available||!1,hasManualMapping:t.has_manual_mapping||!1,energySensor:t.energy_sensor||"",control:t.control||null,controlEntity:t.control?.entity||t.switch_entity||"",controlType:t.control?.type||"switch",controlMode:t.control_mode||"peak_only",dependsOn:t.depends_on||[],goals:t.goals||null,progress:t.progress||null,blockedBy:t.blocked_by||null,soc:t.soc,icon:this._resolveDeviceIcon(t)})).sort((e,t)=>e.priority-t.priority))}render(){if(!this._config)return q;const e=this._getPeakColor(),t=this.targetPeakLimit-this.currentPeak,i=this.targetPeakLimit>0?Math.min(this.currentPeak/this.targetPeakLimit*100,100):0;return W`
            <ha-card>
                <div class="card-content">
                    <div class="status-bar">
                        <div class="peak-dot" style="background:${e};box-shadow:0 0 8px ${e}"></div>
                        <span id="lm-status" class="status-text">${this._t(this.loadManagementStatus||"normal").toUpperCase()}</span>
                        <div class="spacer"></div>
                        <span class="dim">${this._t("peak")}</span>
                        <span id="peak-current" class="mono">${this.currentPeak.toFixed(2)} kW</span>
                        <span class="dim">/ ${this.targetPeakLimit.toFixed(1)}</span>
                        <button class="help-btn ${this._showHelp?"active":""}" data-action="toggle-help"
                                title="${this._t("help")}">?</button>
                    </div>

                    <div class="peak-box">
                        <div class="peak-row">
                            <span class="dim">${this._t("current_peak")}</span>
                            <span id="peak-current2" class="mono">${this.currentPeak.toFixed(2)} kW</span>
                        </div>
                        <div class="peak-row">
                            <span class="dim">${this._t("target_limit")}</span>
                            <span id="peak-target" class="mono">${this.targetPeakLimit.toFixed(2)} kW</span>
                        </div>
                        <div class="peak-row">
                            <span class="dim">${this._t("margin")}</span>
                            <span id="peak-margin" class="mono" style="color:${t>0?"#4caf50":"#f44336"}">${t.toFixed(2)} kW</span>
                        </div>
                        <div class="bar">
                            <div id="peak-bar" class="bar-fill" style="width:${i}%;background:${e}"></div>
                        </div>
                    </div>

                    <div class="peak-box" style="margin-bottom:16px">
                        <span class="dim">${this._t("adjust_target_peak")}</span>
                        <div class="target-row">
                            <input type="number" id="targetInput" min="1" max="20" step="0.1" .value="${String(this.targetPeakLimit)}">
                            <span class="dim">kW</span>
                            <button id="setTargetBtn">${this._t("set")}</button>
                        </div>
                    </div>

                    ${this._showHelp?W`
                    <div class="help-panel">
                        <div class="help-item"><b>${this._t("off")}</b> — ${this._t("help_mode_off")}</div>
                        <div class="help-item"><b>${this._t("peak_only")}</b> — ${this._t("help_mode_peak_only")}</div>
                        <div class="help-item"><b>${this._t("mode_solar_only")}</b> — ${this._t("help_mode_surplus")}</div>
                        <div class="help-item"><b>${this._t("mode_solar_battery")}</b> — ${this._t("battery_overnight_hint")}</div>
                        <div class="help-item"><b>${this._t("priority")}</b> — ${this._t("help_device_priority")}</div>
                        <div class="help-item"><b>${this._t("requires")}</b> — ${this._t("help_device_requires")}</div>
                        <div class="help-item"><b>${this._t("configure")}</b> — ${this._t("help_device_configure")}</div>
                        <div class="help-item"><b>${this._t("target_limit")}</b> — ${this._t("help_device_peak")}</div>
                        <div class="help-item"><b>${this._t("daily_target")}</b> — ${this._t("help_device_target")}</div>
                    </div>`:q}

                    <div class="section-label">
                        <ha-icon icon="mdi:drag-vertical" style="--mdc-icon-size:18px"></ha-icon>
                        ${this._t("drag_to_reorder")}
                    </div>

                    <div id="device-list" class="device-list">
                        ${0===this.devices.length?W`<div class="empty">${this._t("no_devices_yet")}</div>`:Ut(this.devices,e=>e.id,(e,t)=>this._renderDevice(e,t+1))}
                    </div>

                    ${this.devices.length>0?W`<div class="hint">${this._t("drag_hint")}</div>`:q}

                    <div class="hint" style="margin-top:12px;padding:10px;background:rgba(128,128,128,0.06);border-radius:10px">
                        ${this._t("devices_auto_discovered").replace(/<br\s*\/?>/g," — ")}
                    </div>
                </div>
            </ha-card>
        `}_renderDevice(e,t){const i=e.isOn||e.power>.01,s="battery"===e.deviceType,r=e.dependsOn.length>0,a=this._getDependencyDepth(e),o=a>0?`margin-left:${24*a}px;border-left:2px solid rgba(255,152,0,${.3+.1*a});`:"";return W`
        <div class="device${r?" is-child":""}" data-id="${e.id}" style="${o}">
            <div class="drag-handle"
                 title="${r?this._t("locked_under_parent"):this._t("drag_to_reorder")}"
                 @pointerdown=${r?null:t=>this._dragStart(t,e.id)}
                 style="${r?"opacity:0.3;cursor:default":""}">${r?"·":"≡"}</div>
            <div class="device-body">
                <div class="device-top">
                    <div class="device-name">
                        ${r?W`<span style="color:#ff9800;font-size:12px;margin-right:4px">&#8618;</span>`:q}
                        <ha-icon icon="${e.icon}" style="--mdc-icon-size:20px;color:${i?"#ff9800":"#666"}"></ha-icon>
                        <span>${e.name}</span>
                        ${s?q:W`
                        <span class="configure-btn" data-action="configure" data-device="${e.id}" data-name="${e.name}">
                            <ha-icon icon="mdi:${e.hasManualMapping?"wrench":"cog"}" style="--mdc-icon-size:14px"></ha-icon> ${e.isControllable?this._t("configure_device"):this._t("configure")}
                        </span>`}
                    </div>
                    <div class="device-power" data-field="power-${e.id}">
                        ${s?W`<span style="opacity:0.7">${null!=e.soc?e.soc+"% · ":""}${i?ge(1e3*e.power):this._t("off")}</span>`:i?ge(1e3*e.power):e.isShed?this._t("shed_label"):e.rating>0?W`<span style="opacity:0.5" title="${this._t("rated_power_hint")}">~${ge(e.rating)}</span>`:this._t("off")}
                    </div>
                </div>
                ${e.blockedBy?W`<div style="font-size:13px;color:#ff9800;padding:2px 0 0 28px">&#9203; Waiting for: ${e.blockedBy}</div>`:q}
                ${e.dependsOn.length?W`<div style="font-size:13px;opacity:0.55;padding:0 0 0 28px">&#8618; ${this._t("requires")}: ${e.dependsOn.join(", ")}</div>`:q}
                ${e.isShed&&e.shedReason?W`<div style="font-size:13px;color:#f44336;padding:2px 0 0 28px">${"emergency"===e.shedReason?this._t("shed_emergency"):this._t("shed_peak")}</div>`:q}
                <div class="device-bottom">
                    <div class="status-dot ${i?"on":e.isShed?"shed":""}" data-field="status-${e.id}"></div>
                    <span class="dim" data-field="onoff-${e.id}">${i?this._t("on"):e.isShed?this._t("shed_label"):this._t("off")}</span>
                    <span class="badge priority" data-field="pri-${e.id}">${t}</span>
                    <div class="spacer"></div>
                    ${s?W`<span class="dim" title="${this._t("battery_role_help")}">${this._t("battery_role_label")}</span>`:q}
                    ${"ev_charger"===e.deviceType||"ev_charging"===e.deviceType||s?q:W`
                    <label class="toggle-label" title="${this._t("mode_tooltip")}">
                        <span class="dim">${this._t("mode")}</span>
                        <select class="mode-select" data-action="combined_mode" data-device="${e.id}">
                            <option value="off" ?selected="${"off"===this._mergedMode(e)}">${this._t("off")}</option>
                            <option value="peak_only" ?selected="${"peak_only"===this._mergedMode(e)}">${this._t("peak_only")}</option>
                            <option value="solar_only" ?selected="${"solar_only"===this._mergedMode(e)}">${this._t("mode_solar_only")}</option>
                            <option value="solar_battery" ?selected="${"solar_battery"===this._mergedMode(e)}">${this._t("mode_solar_battery")}</option>
                        </select>
                    </label>`}
                    ${s?q:W`
                    <label class="toggle-label" title="${this._t("requires_tooltip")}">
                        <span class="dim">${this._t("requires")}</span>
                        <select class="mode-select" data-action="depends_on" data-device="${e.id}">
                            <option value="" ?selected="${!e.dependsOn.length}">${this._t("action_none")}</option>
                            ${this.devices.filter(t=>t.id!==e.id).map(t=>W`<option value="${t.id}" ?selected="${e.dependsOn.includes(t.id)}">${t.name}</option>`)}
                        </select>
                    </label>`}
                    <div class="arrows">
                        <button class="arrow-btn" data-action="move-up"   data-device="${e.id}" title="${this._t("move_up")}">&#9650;</button>
                        <button class="arrow-btn" data-action="move-down" data-device="${e.id}" title="${this._t("move_down")}">&#9660;</button>
                    </div>
                    ${"ev_charger"===e.deviceType||"ev_charging"===e.deviceType||s||"solar_only"!==this._mergedMode(e)&&"solar_battery"!==this._mergedMode(e)?q:W`
                    <button class="goal-btn ${this._goalOpen[e.id]?"active":""}"
                            data-action="toggle-goal" data-device="${e.id}"
                            title="${this._t("daily_target")}">
                        <ha-icon icon="mdi:target" style="--mdc-icon-size:16px;pointer-events:none"></ha-icon>
                    </button>`}
                </div>
                ${this._renderGoalProgress(e)}
                ${this._goalOpen[e.id]?this._renderGoalEditor(e):q}
            </div>
        </div>`}_mergedMode(e){const t=e.controlMode||"peak_only";return"surplus"!==t?t:(e.goals||{}).battery_assist_enabled?"solar_battery":"solar_only"}_mergedModeLabel(e){const t=this._mergedMode(e),i={off:"off",peak_only:"peak_only",solar_only:"mode_solar_only",solar_battery:"mode_solar_battery"}[t]||t;return this._t(i)}_applyMergedMode(e,t){const i="off"===t||"peak_only"===t?t:"surplus";if(e.controlMode=i,this._sendDeviceUpdate(e.id,"control_mode",i),"surplus"===i){const i="solar_battery"===t;e.goals=e.goals||{},e.goals.battery_assist_enabled=i,this._sendDeviceUpdate(e.id,"battery_assist_enabled",String(i)),"always"===e.goals.top_up_policy&&(e.goals.top_up_policy="solar_only",this._sendDeviceUpdate(e.id,"top_up_policy","solar_only"))}this.requestUpdate()}_hasTarget(e){return parseFloat((e.goals||{}).daily_min_runtime_min)>0}_goalPct(e){const t=e.goals,i=e.progress;if(!t||!i)return null;const s=parseFloat(t.daily_min_runtime_min);return s>0?Math.min(100,i.runtime_today_min/s*100):null}_renderGoalSlider(e){const t=e.goals||{},i=this._goalDrag;let s=(parseFloat(t.daily_min_runtime_min)||0)/60,r=parseFloat(t.daily_max_runtime_min)||0,a=r>0?r/60:12;i&&i.id===e.id&&("min"===i.handle?s=i.value:a=i.value),a<s&&(a=s);const o=Math.min(100,s/12*100),n=Math.min(100,a/12*100),l=a>=11.999999,c=e=>e%1==0?String(e):e.toFixed(1);return W`
            <div class="range-wrap">
                <div class="range-labels">
                    <span>${this._t("at_least")} <b style="color:#8DC892">${s<=0?this._t("no_target"):c(s)+" h"}</b></span>
                    <span>${this._t("up_to")} <b style="color:#ff9800">${l?this._t("uncapped"):c(a)+" h"}</b></span>
                </div>
                <div class="range-track">
                    <div class="range-fill" style="left:${o}%;width:${Math.max(0,n-o)}%;background:linear-gradient(90deg,#8DC892,#ff9800)"></div>
                    <div class="range-handle range-handle-min" style="left:${o}%"
                         @pointerdown=${t=>this._goalSliderStart(t,e,"min")}></div>
                    <div class="range-handle range-handle-max" style="left:${n}%"
                         @pointerdown=${t=>this._goalSliderStart(t,e,"max")}></div>
                </div>
            </div>`}_goalSliderStart(e,t,i){e.stopPropagation(),e.preventDefault();const s=e.currentTarget.parentElement,r=t.goals=t.goals||{},a=s.getBoundingClientRect(),o=(parseFloat(r.daily_min_runtime_min)||0)/60,n=parseFloat(r.daily_max_runtime_min)||0,l=n>0?n/60:12,c=e=>{let t=(e-a.left)/(a.width||1);t=Math.max(0,Math.min(1,t));let s=.5*Math.round(12*t/.5);return s="min"===i?Math.min(s,l):Math.max(s,o),s},d=e=>{this._goalDrag={id:t.id,handle:i,value:c(e)},this.requestUpdate()};d(e.clientX);const p=e=>d(e.clientX),h=e=>{window.removeEventListener("pointermove",p),window.removeEventListener("pointerup",h),window.removeEventListener("pointercancel",h);const s=c(e.clientX);if(this._goalDrag=null,"min"===i){const e=Math.round(60*s);r.daily_min_runtime_min=e,this._sendDeviceUpdate(t.id,"daily_min_runtime_min",String(e))}else{const e=s>=11.999999?0:Math.round(60*s);r.daily_max_runtime_min=e,this._sendDeviceUpdate(t.id,"daily_max_runtime_min",String(e))}this.requestUpdate()};window.addEventListener("pointermove",p),window.addEventListener("pointerup",h),window.addEventListener("pointercancel",h)}_toggleBatteryOvernight(e){const t=e.goals=e.goals||{},i=!t.battery_eligible_overnight;t.battery_eligible_overnight=i,this._sendDeviceUpdate(e.id,"battery_eligible_overnight",String(i)),this.requestUpdate()}_renderGoalProgress(e){const t=this._mergedMode(e);if("solar_only"!==t&&"solar_battery"!==t)return q;const i=this._goalPct(e);if(null===i)return q;const s=e.goals,r=e.progress,a=r.targets_met||i>=100,o=e=>{const t=e/60;return t%1==0?String(t):t.toFixed(1)},n=o(r.runtime_today_min)+"/"+o(parseFloat(s.daily_min_runtime_min))+" "+this._t("hours_on_solar_today");return W`
            <div class="goal-progress" style="padding:2px 0 0 28px">
                <div class="goal-bar"><div class="goal-bar-fill" style="width:${i}%;background:#8DC892"></div></div>
                <span class="goal-progress-text">${n}${a?" ✓":""}</span>
            </div>`}_renderGoalEditor(e){const t=this._mergedMode(e);if("solar_only"!==t&&"solar_battery"!==t)return q;const i=e.goals||{},s=!!i.battery_eligible_overnight;return W`
            <div class="goal-editor">
                <div class="ge-title">
                    <ha-icon icon="mdi:target" style="--mdc-icon-size:14px;color:#8DC892"></ha-icon>
                    ${this._t("daily_target")}
                </div>
                ${this._renderGoalSlider(e)}
                ${"solar_battery"===t?W`
                <div class="ge-row">
                    <span class="ge-label">${this._t("battery_overnight_label")}</span>
                    <span class="ge-ctl">
                        <button class="batt-toggle ${s?"on":""}"
                                data-action="toggle-battery-overnight" data-device="${e.id}"
                                title="${this._t("battery_overnight_help")}">
                            <span class="knob"></span>
                        </button>
                    </span>
                </div>
                <div class="ge-hint">${this._t("battery_overnight_hint")}</div>
                `:W`<div class="ge-hint">${this._t("solar_only_hint")}</div>`}
                <div class="ge-row">
                    <span class="ge-label">${this._t("stop_condition")}</span>
                    <span class="ge-ctl">
                        <input type="text" class="ge-entity" placeholder="${this._t("stop_entity_placeholder")}"
                               .value="${i.stop_entity||""}"
                               data-goal="stop_entity" data-device="${e.id}">
                        <span class="ge-unit">≥</span>
                        <input type="number" min="0" step="1" style="width:56px"
                               .value="${String(i.stop_at||0)}"
                               data-goal="stop_at" data-device="${e.id}">
                    </span>
                </div>
            </div>`}_dragStart(e,t){const i=this.devices.find(e=>e.id===t);if(!i||i.dependsOn&&i.dependsOn.length)return;if(null!=e.button&&0!==e.button)return;e.preventDefault();const s=e.currentTarget,r=s.closest(".device"),a=this.renderRoot.getElementById("device-list");if(!r||!a)return;const o=Array.from(a.querySelectorAll(".device")),n=o.map(e=>{const t=e.getBoundingClientRect();return t.top+t.height/2});this._interacting=!0;const l=o.indexOf(r);this._drag={id:t,handle:s,row:r,rows:o,centres:n,pointerY0:e.clientY,fromIndex:l,dropIndex:l,pointerId:e.pointerId},r.classList.add("dragging-row");try{s.setPointerCapture(e.pointerId)}catch(e){}this._dragMoveBound=this._dragMoveBound||this._dragMove.bind(this),this._dragEndBound=this._dragEndBound||this._dragEnd.bind(this),window.addEventListener("pointermove",this._dragMoveBound),window.addEventListener("pointerup",this._dragEndBound),window.addEventListener("pointercancel",this._dragEndBound)}_dragMove(e){const t=this._drag;if(!t)return;e.preventDefault(),t.row.style.transform=`translateY(${e.clientY-t.pointerY0}px)`;const i=function(e,t,i){let s=0;for(let r=0;r<e.length;r++)r!==t&&i>e[r]&&s++;return s}(t.centres,t.fromIndex,e.clientY);i!==t.dropIndex&&(t.dropIndex=i,this._paintDropLine(t,i))}_paintDropLine(e,t){e.rows.forEach(e=>e.classList.remove("drop-above","drop-below"));const i=e.rows[t<e.fromIndex?t:t+1];i&&i!==e.row?i.classList.add("drop-above"):e.rows[e.rows.length-1]?.classList.add("drop-below")}_dragEnd(e){const t=this._drag;if(t){window.removeEventListener("pointermove",this._dragMoveBound),window.removeEventListener("pointerup",this._dragEndBound),window.removeEventListener("pointercancel",this._dragEndBound);try{t.handle.releasePointerCapture(t.pointerId)}catch(e){}t.row.style.transform="",t.row.classList.remove("dragging-row"),t.rows.forEach(e=>e.classList.remove("drop-above","drop-below")),this._interacting=!1,this._drag=null,"pointercancel"!==e.type&&t.dropIndex!==t.fromIndex&&this._moveDeviceToIndex(t.id,t.dropIndex)}}_moveDeviceToIndex(e,t){this.devices=function(e,t,i){const s=e.slice(),r=s.findIndex(e=>e.id===t);if(-1===r)return s;const[a]=s.splice(r,1),o=Math.max(0,Math.min(i,s.length));return s.splice(o,0,a),function(e){return e.forEach((e,t)=>{e.priority=t+1}),e}(Ht(s))}(this.devices,e,t),this.requestUpdate(),this._sendPriorityUpdate()}_bindEvents(){const e=this.renderRoot,t=e.getElementById("setTargetBtn");t&&!t._semBound&&(t._semBound=!0,t.addEventListener("click",()=>{const t=e.getElementById("targetInput"),i=parseFloat(t?.value);i&&i>0&&i<=20&&(this.targetPeakLimit=i,this._sendTargetPeakUpdate(i),this.requestUpdate())}));const i=e=>{const t=e.target.closest("[data-action]");if(!t)return;const i=t.dataset.action,s=t.dataset.device;if("controllable"===i){const e=this.devices.find(e=>e.id===s);e&&(e.isControllable=!e.isControllable,this._sendDeviceUpdate(s,"controllable",e.isControllable),this.requestUpdate())}else if("move-up"===i||"move-down"===i)this._moveDevice(s,"move-up"===i?-1:1);else if("configure"===i)this._showConfigureModal(s,t.dataset.name);else if("toggle-help"===i)this._showHelp=!this._showHelp,this.requestUpdate();else if("toggle-goal"===i)this._goalOpen[s]=!this._goalOpen[s],this.requestUpdate();else if("toggle-battery-overnight"===i){const e=this.devices.find(e=>e.id===s);e&&this._toggleBatteryOvernight(e)}},s=e=>{const t=e.target.closest('[data-action="combined_mode"]');if(t){const e=t.dataset.device,i=this.devices.find(t=>t.id===e);return void(i&&this._applyMergedMode(i,t.value))}const i=e.target.closest("[data-goal]");if(i){const e=i.dataset.device,t=i.dataset.goal;let s=i.value;const r=this.devices.find(t=>t.id===e);return r&&(r.goals=r.goals||{},r.goals[t]=s),void this._sendDeviceUpdate(e,t,String(s))}const s=e.target.closest('[data-action="depends_on"]');if(s){const e=s.dataset.device,t=this.devices.find(t=>t.id===e);if(t){const i=s.value;t.dependsOn=i?[i]:[],this._sendDeviceUpdate(e,"depends_on",i),this._regroupChildren(),this.devices.forEach((e,t)=>{e.priority=t+1}),this.requestUpdate(),this._sendPriorityUpdate()}}},r=e.querySelector("ha-card");r&&!r._semEvtBound&&(r._semEvtBound=!0,r.addEventListener("click",i),r.addEventListener("change",s))}_moveDevice(e,t){const i=this.devices.findIndex(t=>t.id===e);if(-1===i)return;const s=i+t;s<0||s>=this.devices.length||this.devices[i].dependsOn.length||this._moveDeviceToIndex(e,s)}_getDependencyDepth(e){let t=0,i=e;const s=new Set;for(;i.dependsOn.length>0&&t<5;){s.add(i.id);const e=i.dependsOn[0];if(s.has(e))break;const r=this.devices.find(t=>t.id===e);if(!r)break;t++,i=r}return t}_regroupChildren(){this.devices=Ht(this.devices)}_sendPriorityUpdate(){this._hass&&(this._hass.callService("solar_energy_management","update_device_priorities",{priorities:this.devices.map(e=>({device_id:e.id,priority:e.priority}))}),this._priorityFrozenUntil=Date.now()+15e3)}_sendDeviceUpdate(e,t,i){this._hass&&this._hass.callService("solar_energy_management","update_device_config",{device_id:e,property:t,value:i})}_sendTargetPeakUpdate(e){this._hass&&this._hass.callService("solar_energy_management","update_target_peak",{target_peak_limit:e})}async _ensureEntityPicker(){if(!customElements.get("ha-entity-picker"))try{const e=await(window.loadCardHelpers?.());if(e?.createCardElement){const t=await e.createCardElement({type:"entities",entities:[]});await(t.constructor?.getConfigElement?.())}}catch(e){}}async _showConfigureModal(e,t){const i=this.renderRoot.getElementById("sem-config-modal");i&&i.remove();const s=function(e,t){return(e||[]).find(e=>e.id===t)||null}(this.devices,e),r=s?.energySensor||"",a=function(e){const t=e||{};return{type:Wt.includes(t.type)?t.type:"switch",entity:t.entity||"",service:t.service||"",param:t.param||"current",shed_value:null!=t.shed_value?t.shed_value:0,restore_value:null!=t.restore_value?t.restore_value:16}}(s?.control),o="manual_mapping"===s?.control?.discovered_via;await this._ensureEntityPicker();const n=document.createElement("div");n.id="sem-config-modal",n.style.cssText="position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:999;display:flex;align-items:center;justify-content:center",n.innerHTML=function({deviceName:e,values:t,t:i,hasManual:s=!1}){const r=t,a="service"===r.type,o=(e,t)=>`<option value="${e}" ${r.type===e?"selected":""}>${t}</option>`;return`\n        <div style="background:var(--card-background-color,#1e1e2e);border-radius:12px;padding:24px;min-width:320px;max-width:90vw;color:var(--primary-text-color,#e0e0e0)">\n            <div style="font-weight:700;margin-bottom:16px">${i("configure_device")}: ${Gt(e)}</div>\n            <label style="font-size:13px;opacity:0.7">${i("control_type")}</label>\n            <select id="cfg-type" style="${qt}">\n                ${o("switch",i("mode_switch"))}\n                ${o("current",i("mode_current"))}\n                ${o("input_boolean",i("mode_input_boolean"))}\n                ${o("service",i("mode_service"))}\n            </select>\n            <div id="cfg-entity-group" style="display:${a?"none":"block"}">\n                <label style="font-size:13px;opacity:0.7">${i("control_entity")}</label>\n                <input id="cfg-entity" type="text" placeholder="switch.example" value="${Gt(r.entity)}" style="${qt}">\n            </div>\n            <div id="cfg-service-group" style="display:${a?"block":"none"}">\n                <label style="font-size:13px;opacity:0.7">${i("svc_service")}</label>\n                <input id="cfg-service" type="text" placeholder="keba.set_current" value="${Gt(r.service)}" style="${qt}">\n                <label style="font-size:13px;opacity:0.7">${i("svc_param")}</label>\n                <input id="cfg-param" type="text" placeholder="current" value="${Gt(r.param)}" style="${qt}">\n                <div style="display:flex;gap:8px">\n                    <div style="flex:1">\n                        <label style="font-size:13px;opacity:0.7">${i("svc_shed_value")}</label>\n                        <input id="cfg-shed" type="number" value="${Gt(r.shed_value)}" style="${qt}">\n                    </div>\n                    <div style="flex:1">\n                        <label style="font-size:13px;opacity:0.7">${i("svc_restore_value")}</label>\n                        <input id="cfg-restore" type="number" value="${Gt(r.restore_value)}" style="${qt}">\n                    </div>\n                </div>\n            </div>\n            <div class="cfg-error" style="color:#f44336;font-size:13px;margin:4px 0 8px;display:none"></div>\n            <div style="display:flex;gap:8px;align-items:center">\n                ${s?`<button id="cfg-remove" style="padding:8px 12px;border-radius:6px;border:none;cursor:pointer;background:transparent;color:#f44336">${i("clear_mapping")}</button>`:""}\n                <div style="flex:1"></div>\n                <button id="cfg-cancel" style="padding:8px 16px;border-radius:6px;border:none;cursor:pointer;background:rgba(255,255,255,0.1);color:inherit">${i("cancel")}</button>\n                <button id="cfg-save" style="padding:8px 16px;border-radius:6px;border:none;cursor:pointer;background:#4caf50;color:white">${i("save")}</button>\n            </div>\n        </div>`}({deviceName:t,values:a,t:e=>this._t(e),hasManual:o}),this.renderRoot.appendChild(n);const l=n.querySelector("#cfg-type"),c=n.querySelector("#cfg-entity-group"),d=n.querySelector("#cfg-service-group"),p=n.querySelector("#cfg-entity"),h=n.querySelector(".cfg-error"),_=e=>{h.textContent=e,h.style.display="block"};let g=null;customElements.get("ha-entity-picker")&&(g=document.createElement("ha-entity-picker"),g.hass=this._hass,g.allowCustomEntity=!0,g.value=p.value,g.includeDomains=jt[l.value],g.style.cssText="display:block;margin:6px 0 12px",g.addEventListener("value-changed",e=>{p.value=e.detail.value||""}),p.style.display="none",p.parentNode.insertBefore(g,p));l.addEventListener("change",()=>{const e="service"===l.value;c.style.display=e?"none":"block",d.style.display=e?"block":"none",g&&!e&&(g.includeDomains=jt[l.value])}),n.addEventListener("click",e=>{e.target===n&&n.remove()}),n.querySelector("#cfg-cancel").addEventListener("click",()=>n.remove());const u=n.querySelector("#cfg-remove");u&&u.addEventListener("click",()=>{this._hass.callService("solar_energy_management","remove_device_control_mapping",{energy_sensor:r}).then(()=>{s&&(s.control=null,this.requestUpdate()),n.remove()}).catch(e=>_(e.message))}),n.querySelector("#cfg-save").addEventListener("click",()=>{const e=function(e){const t=t=>e.querySelector("#"+t);return{type:t("cfg-type")?.value||"switch",entity:(t("cfg-entity")?.value||"").trim(),service:(t("cfg-service")?.value||"").trim(),param:(t("cfg-param")?.value||"").trim()||"current",shed_value:t("cfg-shed")?.value,restore_value:t("cfg-restore")?.value}}(n);let t;g&&(e.entity=(g.value||"").trim());try{t=function(e,t){const i=Wt.includes(t.type)?t.type:"switch";if("service"===i){if(!t.service)throw new Error("mapping_service_required");return{energy_sensor:e,control_type:"service",service:t.service,param:t.param||"current",shed_value:Number(t.shed_value),restore_value:Number(t.restore_value)}}if(!t.entity)throw new Error("mapping_entity_required");return{energy_sensor:e,control_type:i,control_entity:t.entity}}(r,e)}catch(e){return void _(this._t(e.message))}this._hass.callService("solar_energy_management","set_device_control_mapping",t).then(()=>{s&&(s.control="service"===t.control_type?{type:"service",service:t.service,param:t.param,shed_value:t.shed_value,restore_value:t.restore_value,discovered_via:"manual_mapping"}:{type:t.control_type,entity:t.control_entity,discovered_via:"manual_mapping"},this.requestUpdate()),n.remove()}).catch(e=>_(e.message))})}_getPeakColor(){const e=this.targetPeakLimit>0?this.currentPeak/this.targetPeakLimit*100:0;return e>=100?"#f44336":e>=90?"#ff9800":e>=70?"#2196f3":"#4caf50"}_resolveDeviceIcon(e){for(const t of[e.switch_entity,e.power_entity,e.control?.entity])if(t){const e=this._hass?.states[t];if(e?.attributes?.icon)return e.attributes.icon}return{ev_charger:"mdi:ev-station",ev_charging:"mdi:ev-station",battery:"mdi:home-battery",heating:"mdi:radiator",heat_pump:"mdi:heat-pump",water_heater:"mdi:water-boiler",hot_water:"mdi:water-boiler",pool_pump:"mdi:pool",appliance:"mdi:washing-machine",climate:"mdi:thermostat",light:"mdi:lightbulb",printer:"mdi:printer",computer:"mdi:desktop-classic",network:"mdi:network",fan:"mdi:fan",dryer:"mdi:tumble-dryer",dishwasher:"mdi:dishwasher",freezer:"mdi:fridge",refrigerator:"mdi:fridge"}[e.device_type]||"mdi:power-plug"}getCardSize(){return Math.max(5,3+this.devices.length)}static getStubConfig(){return{entity_prefix:"sensor.sem_"}}},{type:"sem-load-priority-card",name:"SEM Load Priority Card",description:"Drag and drop interface for managing load shedding priorities",preview:!0});const Kt=[{id:"surplus",icon:"mdi:solar-power",color:"#ff9800",titleKey:"surplus_control",subtitleFn:e=>{const t=e._valNum("surplus_active_devices").toFixed(0),i=e._valNum("surplus_total_devices").toFixed(0),s=e._valNum("surplus_allocated_w").toFixed(0);return`${t}/${i} ${e._t("devices")} · ${s}W`}},{id:"battery",icon:"mdi:battery-medium",color:"#4db6ac",titleKey:"battery_management",subtitleFn:e=>{const t=e._valNum("battery_soc").toFixed(0),i=e._val("battery_status")||"";return`SOC ${t}% · ${i?e._t(i.toLowerCase()):"—"}`}},{id:"hotwater",icon:"mdi:water-thermometer",color:"#f06292",titleKey:"hot_water_title",subtitleFn:()=>""},{id:"heatpump",icon:"mdi:heat-pump",color:"#4db6ac",titleKey:"heat_pump_title",subtitleFn:e=>{if(!e._bin("heat_pump_registered"))return"";const t=e._val("heat_pump_sg_ready_state"),i=e._val("heat_pump_mode");return t?`${i||"—"} · ${t}`:""}},{id:"tariff",icon:"mdi:cash-multiple",color:"#96CAEE",titleKey:"tariff_pricing",subtitleFn:e=>{const t=e._val("tariff_provider")||"—",i=e._val("tariff_price_level")||"";return i?`${t} · ${e._t(i.toLowerCase())}`:t}},{id:"peak",icon:"mdi:flash-alert",color:"#ff9800",titleKey:"peak_load_management",subtitleFn:e=>{const t=e._valNum("consecutive_peak_15min").toFixed(1),i=e._valNum("monthly_consecutive_peak").toFixed(1);return`${e._t("peak")} ${t} kW · ${e._t("monthly_peak")} ${i} kW`}}],Vt=["sensor.sem_surplus_active_devices","sensor.sem_surplus_total_devices","sensor.sem_surplus_allocated_w","sensor.sem_surplus_total_w","sensor.sem_surplus_distributable_w","sensor.sem_surplus_unallocated_w","sensor.sem_battery_soc","sensor.sem_battery_status","sensor.sem_diag_battery_capacity","number.sem_legionella_target_temp","binary_sensor.sem_heat_pump_registered","sensor.sem_heat_pump_sg_ready_state","sensor.sem_heat_pump_mode","binary_sensor.sem_heat_pump_solar_boost","sensor.sem_tariff_provider","sensor.sem_tariff_price_level","sensor.sem_tariff_current_import_rate","sensor.sem_consecutive_peak_15min","sensor.sem_monthly_consecutive_peak","sensor.sem_current_vs_peak_percentage","sensor.sem_load_management_status","sensor.sem_load_management_recommendation","sensor.sem_peak_margin","sensor.sem_available_load_reduction","sensor.sem_controllable_devices_count","switch.sem_observer_mode"];$e("sem-control-card",class extends ke{static get watchedEntities(){return Vt}static get properties(){return{...super.properties}}constructor(){super(),this._collapsed={surplus:!0,battery:!1,hotwater:!0,heatpump:!0,tariff:!1,peak:!0}}setConfig(e){super.setConfig(e),this._prefix=e.entity_prefix||"sensor.sem_"}_val(e){const t=this._hass?.states[`${this._prefix}${e}`];return t&&"unavailable"!==t.state&&"unknown"!==t.state?t.state:""}_valNum(e,t=0){const i=this._hass?.states[`${this._prefix}${e}`];return i&&"unavailable"!==i.state&&"unknown"!==i.state?parseFloat(i.state)??t:t}_numVal(e,t=0){const i=this._hass?.states[`number.sem_${e}`];return i&&"unavailable"!==i.state&&"unknown"!==i.state?parseFloat(i.state)??t:t}_switchOn(e){return"on"===this._hass?.states[`switch.sem_${e}`]?.state}_bin(e){return"on"===this._hass?.states[`binary_sensor.sem_${e}`]?.state}_toggleSection(e){this._collapsed={...this._collapsed,[e]:!this._collapsed[e]},this.requestUpdate()}_renderStepper(e,t,i,s){const r=this._hass?.states[e];if(!r)return q;const a=this._frozenEntities[e],o=a?a.value:parseFloat(r.state)||0,n=parseFloat(r.attributes.step)||1,l=r.attributes.unit_of_measurement||"",c=n<1?1:0,d=o.toFixed(c)+(l?" "+l:"");return W`
            <div class="stepper-cell">
                <div class="stepper-row">
                    <span class="stepper-label">${this._t(t)}</span>
                    <div class="stepper-controls">
                        <button
                            class="stepper-minus" aria-label="Decrease"
                            @click=${()=>this._stepNumber(e,-1)}
                            @pointerdown=${()=>this._startHold(e,-1)}
                            @pointerup=${()=>this._stopHold(e)}
                            @pointerleave=${()=>this._stopHold(e)}
                        >−</button>
                        <span class="stepper-value">${d}</span>
                        <button
                            class="stepper-plus" aria-label="Increase"
                            @click=${()=>this._stepNumber(e,1)}
                            @pointerdown=${()=>this._startHold(e,1)}
                            @pointerup=${()=>this._stopHold(e)}
                            @pointerleave=${()=>this._stopHold(e)}
                        >+</button>
                    </div>
                </div>
                ${this._showHelp&&s?W`<div class="setting-help-text">${this._t(s)}</div>`:q}
            </div>
        `}_renderSelect(e,t,i){const s=this._hass?.states[e];if(!s)return q;const r=this._frozenEntities[e],a=r?r.value:s.state,o=s.attributes.options||[];return W`
            <div class="ctrl-row">
                <span class="ctrl-label">${this._t(t)}</span>
                <select
                    class="sem-select"
                    .value=${a}
                    @change=${t=>this._selectOption(e,t.target.value)}
                >
                    ${o.map(e=>W`<option value="${e}" ?selected=${e===a}>${e}</option>`)}
                </select>
            </div>
        `}_renderSurplusSection(e){const t=this._valNum("surplus_total_w").toFixed(0),i=this._valNum("surplus_distributable_w").toFixed(0),s=this._valNum("surplus_allocated_w").toFixed(0),r=this._valNum("surplus_unallocated_w").toFixed(0);return W`
            <div class="info-tiles">
                <div class="info-tile">
                    <ha-icon icon="mdi:solar-power" style="--mdc-icon-size:18px;color:#ff9800"></ha-icon>
                    <div class="info-tile-content">
                        <span class="info-tile-label">${this._t("surplus_available")}</span>
                        <span class="info-tile-values">
                            <span>${t}W</span>
                            <span class="info-tile-sep">·</span>
                            <span>${i}W</span>
                        </span>
                    </div>
                </div>
                <div class="info-tile">
                    <ha-icon icon="mdi:chart-pie" style="--mdc-icon-size:18px;color:#8DC892"></ha-icon>
                    <div class="info-tile-content">
                        <span class="info-tile-label">${this._t("surplus_allocation")}</span>
                        <span class="info-tile-values">
                            <span>${s}W</span>
                            <span class="info-tile-sep">·</span>
                            <span>${r}W</span>
                        </span>
                    </div>
                </div>
            </div>
        `}_renderBatterySection(e){const t=this._valNum("diag_battery_capacity"),i=t>0?t.toFixed(1)+" kWh":"—",s=this._val("diag_grid_sign")||"—";return W`
            <div class="readonly-row">
                <span class="ctrl-label">${this._t("capacity_kwh")}</span>
                <span class="readonly-value">${i}</span>
            </div>
            <div class="readonly-row">
                <span class="ctrl-label">${this._t("grid_sign")}</span>
                <span class="readonly-value">${s}</span>
            </div>
        `}_renderHeatPumpSection(e){if(!this._bin("heat_pump_registered"))return W`<div class="info-box-text" style="opacity:0.6">
                ${this._t("heat_pump_not_configured")}
            </div>`;const t=this._val("heat_pump_sg_ready_state"),i=this._val("heat_pump_mode")||"—",s=this._switchOn("heat_pump_solar_boost")?"#ff9800":"#4db6ac";return W`
            <div class="readonly-row">
                <ha-icon icon="mdi:heat-pump-outline" style="--mdc-icon-size:18px;color:${s}"></ha-icon>
                <span class="ctrl-label" style="flex:1">${this._t("heat_pump_mode")}</span>
                <span class="readonly-value">${this._t(i.toLowerCase())||i}</span>
            </div>
            <div class="readonly-row">
                <ha-icon icon="mdi:transmission-tower" style="--mdc-icon-size:18px;color:${s}"></ha-icon>
                <span class="ctrl-label" style="flex:1">${this._t("heat_pump_sg_ready_state")}</span>
                <span class="readonly-value">${t}</span>
            </div>
        `}_renderHotWaterSection(e){return W`
            ${this._renderStepper("number.sem_legionella_target_temp","legionella_target",e)}
            <div class="info-box">
                <ha-icon icon="mdi:shield-alert" style="--mdc-icon-size:16px;color:#ff9800"></ha-icon>
                <div>
                    <div class="info-box-title">${this._t("legionella_prevention")}</div>
                    <div class="info-box-text">
                        DE (DVGW W 551): ≥ 60°C · CH (SIA 385/1): ≥ 60°C · AT (ÖNORM B 5019): 60°C / 70°C 3 min
                    </div>
                </div>
            </div>
        `}_renderTariffSection(e){const t=this._hass?.states["sensor.sem_tariff_current_import_rate"],i=t?t.state:"—",s=t?.attributes?.unit_of_measurement||"";return W`
            <div class="readonly-row tariff-rate-row">
                <ha-icon icon="mdi:flash" style="--mdc-icon-size:18px;color:#ff9800"></ha-icon>
                <span class="ctrl-label" style="flex:1">${this._t("current_electricity_price")}</span>
                <span class="readonly-value tariff-rate-value">${i} ${s}</span>
            </div>
        `}_renderPeakSection(e){const t=this._valNum("current_vs_peak_percentage"),i=t>90?"#f44336":t>70?"#ff9800":"#8DC892",s=this._valNum("controllable_devices_count").toFixed(0),r=this._valNum("available_load_reduction");return W`
            <div class="peak-hero">
                <span class="peak-pct" style="color:${i}">${t.toFixed(0)}%</span>
                <span class="peak-of-limit">${this._t("of_limit")}</span>
            </div>
            <div class="peak-detail">
                <span class="peak-status">${(()=>{const e=this._val("load_management_status");return e?this._t(e):"—"})()}</span>
                <span class="peak-sep">·</span>
                <span class="peak-rec">${(()=>{const e=this._val("load_management_recommendation");return e?this._t(e):""})()}</span>
            </div>
            <div class="info-tiles">
                <div class="info-tile">
                    <ha-icon icon="mdi:shield-check" style="--mdc-icon-size:18px;color:#8DC892"></ha-icon>
                    <div class="info-tile-content">
                        <span class="info-tile-label">${this._t("peak_margin")}</span>
                        <span class="info-tile-value">${this._valNum("peak_margin").toFixed(1)} kW</span>
                    </div>
                </div>
                <div class="info-tile">
                    <ha-icon icon="mdi:power-plug-off" style="--mdc-icon-size:18px;color:#ff9800"></ha-icon>
                    <div class="info-tile-content">
                        <span class="info-tile-label">${this._t("sheddable")}</span>
                        <span class="info-tile-value">${r.toFixed(1)} kW · ${s} ${this._t("devices")}</span>
                    </div>
                </div>
            </div>
        `}_renderSectionHeader(e,t){const i=this._collapsed[e.id],s=i?"rotate(-90deg)":"rotate(0deg)";return W`
            <div
                class="section-header"
                tabindex="0"
                role="button"
                aria-expanded="${!i}"
                @click=${()=>this._toggleSection(e.id)}
                @keydown=${t=>{"Enter"!==t.key&&" "!==t.key||(t.preventDefault(),this._toggleSection(e.id))}}
            >
                <ha-icon icon="${e.icon}" style="--mdc-icon-size:20px;color:${e.color}"></ha-icon>
                <span class="section-title-text">${this._t(e.titleKey)}</span>
                <span class="section-subtitle">${e.subtitleFn(this)}</span>
                <ha-icon
                    class="chevron"
                    icon="mdi:chevron-down"
                    style="--mdc-icon-size:18px;transform:${s}"
                ></ha-icon>
            </div>
        `}_renderSection(e,t,i){const s=this._collapsed[e.id];return W`
            <div class="section ${s?"":"expanded"}"
                 style="--section-accent: ${e.color}">
                ${this._renderSectionHeader(e,i)}
                <div class="section-content ${s?"":"expanded"}">
                    <div class="section-body">
                        ${t(i)}
                    </div>
                </div>
            </div>
        `}render(){if(!this._config)return q;const e=this._theme(),t=!1!==e.isDark,i=e.accent||"#42a5f5",s=this._switchOn("observer_mode"),r={surplus:e=>this._renderSurplusSection(e),battery:e=>this._renderBatterySection(e),hotwater:e=>this._renderHotWaterSection(e),heatpump:e=>this._renderHeatPumpSection(e),tariff:e=>this._renderTariffSection(e),peak:e=>this._renderPeakSection(e)};return W`
            <style>
                :host { display: block; contain: layout style paint; }
                .wrap {
                    padding: 16px;
                    position: relative;
                    background:
                        radial-gradient(ellipse 70% 60% at 50% 25%, rgba(150,202,238,0.06) 0%, transparent 100%),
                        radial-gradient(circle at 2px 2px, ${e.dotColor} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${e.text});
                }

                /* ── Observer warning ── */
                .observer-warning {
                    display: flex; align-items: center; gap: 10px;
                    border-radius: 12px;
                    background: radial-gradient(ellipse 60% 50% at 50% 40%, rgba(244,67,54,0.12) 0%, transparent 100%);
                    border: 1px solid rgba(244,67,54,0.35);
                    color: #f44336;
                    font-size: 13px; font-weight: 500;
                    overflow: hidden;
                    transition: max-height 0.3s ease, opacity 0.2s ease, margin-bottom 0.3s ease, padding 0.3s ease;
                    max-height: ${s?"60px":"0"};
                    opacity: ${s?"1":"0"};
                    margin-bottom: ${s?"12px":"0"};
                    padding: ${s?"12px 16px":"0 16px"};
                }

                /* ── Sections (polish: color accent + EV-card-matching typography) ── */
                .section {
                    margin-bottom: 10px;
                    border-radius: 14px;
                    background: ${e.surface};
                    border: 1px solid ${e.surfaceBorder};
                    overflow: hidden;
                    transition: border-color 0.2s, box-shadow 0.2s;
                    position: relative;
                }
                /* When expanded: subtle color-coded accent stripe matching the
                   section icon's color, plus a soft glow that ties the card
                   together with the EV card's hint-row aesthetic. */
                .section.expanded {
                    border-color: color-mix(in srgb, var(--section-accent) 40%, ${e.surfaceBorder});
                    box-shadow: inset 3px 0 0 0 var(--section-accent);
                }
                .section:hover { border-color: ${t?"rgba(255,255,255,0.18)":"rgba(0,0,0,0.12)"}; }

                .section-header {
                    display: flex; align-items: center; gap: 10px;
                    padding: 13px 14px;
                    cursor: pointer;
                    user-select: none;
                    -webkit-user-select: none;
                    transition: background 0.15s;
                }
                .section-header:hover { background: ${e.surfaceHover}; }
                .section.expanded .section-header {
                    background: color-mix(in srgb, var(--section-accent) 6%, transparent);
                }
                .section-title-text {
                    font-size: 15px; font-weight: 600;
                    white-space: nowrap;
                    letter-spacing: 0.1px;
                }
                .section-subtitle {
                    flex: 1;
                    font-size: 13px;
                    color: var(--secondary-text-color, ${e.textSec});
                    text-align: right;
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    margin-right: 4px;
                }
                .chevron {
                    transition: transform 0.25s ease;
                    color: var(--secondary-text-color, ${e.textSec});
                    flex-shrink: 0;
                }

                /* ── Collapsible content ── */
                .section-content {
                    max-height: 0;
                    opacity: 0;
                    overflow: hidden;
                    transition: max-height 0.3s ease, opacity 0.2s ease;
                }
                .section-content.expanded {
                    max-height: 1000px;
                    opacity: 1;
                }
                .section-body { padding: 0 14px 14px; }

                .stepper-cell { display: flex; flex-direction: column; }

                /* ── Select ── */
                .ctrl-row {
                    display: flex; align-items: center; justify-content: space-between;
                    padding: 8px 0;
                    border-bottom: 1px solid ${e.surfaceBorder};
                    margin-bottom: 4px;
                }
                .ctrl-label { font-size: 14px; font-weight: 500; }
                .sem-select {
                    background: ${e.surface};
                    border: 1px solid ${e.surfaceBorder};
                    border-radius: 8px;
                    color: var(--primary-text-color, ${e.text});
                    padding: 6px 10px;
                    font-size: 14px;
                    font-family: inherit;
                    cursor: pointer;
                    min-width: 120px;
                    outline: none;
                }
                .sem-select:focus { border-color: ${i}; }
                .sem-select option {
                    background: ${t?"#1e232d":"#fff"};
                    color: ${t?"#e0e0e0":"#333"};
                }

                /* ── Number stepper ── */
                .stepper-row {
                    display: flex; align-items: center; justify-content: space-between;
                    padding: 7px 0;
                }
                .stepper-label {
                    font-size: 14px; font-weight: 500;
                    flex: 1; min-width: 0;
                    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
                }
                .stepper-controls { display: flex; align-items: center; gap: 2px; flex-shrink: 0; }
                .stepper-minus, .stepper-plus {
                    width: 30px; height: 30px;
                    border-radius: 8px;
                    border: 1px solid ${e.surfaceBorder};
                    background: ${e.surface};
                    color: var(--primary-text-color, ${e.text});
                    font-size: 16px; font-weight: 600;
                    cursor: pointer;
                    display: flex; align-items: center; justify-content: center;
                    transition: background 0.15s, border-color 0.15s;
                    user-select: none; -webkit-user-select: none;
                    touch-action: manipulation;
                    padding: 0; line-height: 1;
                }
                .stepper-minus:hover, .stepper-plus:hover {
                    background: ${e.surfaceHover};
                    border-color: ${i};
                }
                .stepper-minus:active, .stepper-plus:active {
                    background: ${t?"rgba(255,255,255,0.15)":"rgba(0,0,0,0.08)"};
                }
                .stepper-value {
                    font-size: 14px; font-weight: 600;
                    min-width: 60px; text-align: center;
                    font-variant-numeric: tabular-nums;
                }
                .stepper-pair {
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                    gap: 0 16px;
                }
                @media (max-width: 480px) { .stepper-pair { grid-template-columns: 1fr; } }

                /* ── Read-only row ── */
                .readonly-row {
                    display: flex; align-items: center; justify-content: space-between;
                    padding: 7px 0;
                }
                .readonly-value {
                    font-size: 14px; font-weight: 600;
                    font-variant-numeric: tabular-nums;
                    color: var(--secondary-text-color, ${e.textSec});
                }
                .tariff-rate-row {
                    gap: 8px;
                    border-bottom: 1px solid ${e.surfaceBorder};
                    margin-bottom: 8px; padding-bottom: 10px;
                }
                .tariff-rate-value { font-size: 15px; font-weight: 700; color: ${e.text}; }

                /* ── Info tiles (surplus, peak) ── */
                .info-tiles {
                    display: grid; grid-template-columns: 1fr 1fr;
                    gap: 8px; margin: 8px 0;
                }
                .info-tile {
                    display: flex; align-items: flex-start; gap: 8px;
                    padding: 10px; border-radius: 10px;
                    background: ${t?"rgba(255,255,255,0.03)":"rgba(0,0,0,0.02)"};
                    border: 1px solid ${e.surfaceBorder};
                }
                .info-tile ha-icon { margin-top: 1px; flex-shrink: 0; }
                .info-tile-content { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
                .info-tile-label {
                    font-size: 11px; font-weight: 500; text-transform: uppercase;
                    color: var(--secondary-text-color, ${e.textSec});
                    letter-spacing: 0.3px;
                }
                .info-tile-values { font-size: 13px; font-weight: 600; display: flex; gap: 4px; flex-wrap: wrap; }
                .info-tile-value { font-size: 13px; font-weight: 600; }
                .info-tile-sep { color: var(--secondary-text-color, ${e.textSec}); }
                @media (max-width: 480px) { .info-tiles { grid-template-columns: 1fr; } }

                /* ── Info box (legionella) ── */
                .info-box {
                    display: flex; gap: 8px;
                    padding: 10px 12px; border-radius: 10px;
                    background: ${t?"rgba(255,152,0,0.06)":"rgba(255,152,0,0.05)"};
                    border: 1px solid rgba(255,152,0,0.2);
                    margin-top: 8px;
                }
                .info-box ha-icon { flex-shrink: 0; margin-top: 1px; }
                .info-box-title { font-size: 12px; font-weight: 600; margin-bottom: 2px; }
                .info-box-text {
                    font-size: 11px; line-height: 1.4;
                    color: var(--secondary-text-color, ${e.textSec});
                }

                /* ── Peak hero ── */
                .peak-hero {
                    display: flex; align-items: baseline; justify-content: center;
                    gap: 6px; padding: 4px 0;
                }
                .peak-pct { font-size: 28px; font-weight: 700; font-variant-numeric: tabular-nums; }
                .peak-of-limit {
                    font-size: 12px; font-weight: 500;
                    color: var(--secondary-text-color, ${e.textSec});
                    text-transform: uppercase;
                }
                .peak-detail {
                    text-align: center; padding: 0 0 8px;
                    font-size: 12px;
                    color: var(--secondary-text-color, ${e.textSec});
                }
                .peak-sep { margin: 0 4px; }
            </style>
            <div class="wrap">
                <div class="observer-warning">
                    <ha-icon icon="mdi:eye-outline" style="--mdc-icon-size:20px;color:#f44336"></ha-icon>
                    <span>${this._t("observer_mode_active")} — ${this._t("observer_mode_readonly")}</span>
                </div>
                ${Kt.map(t=>this._renderSection(t,r[t.id],e))}
            </div>
        `}getCardSize(){return 12}static getStubConfig(){return{entity_prefix:"sensor.sem_"}}},{type:"custom:sem-control-card",name:"SEM Control Card",description:"Consolidated control panel for Solar Energy Management",preview:!1});class Yt extends ce{static get properties(){return{hass:{type:Object},entryId:{type:String,attribute:"entry-id"},optionKey:{type:String,attribute:"option-key"},chargerIndex:{type:Number,attribute:"charger-index"},chargerKey:{type:String,attribute:"charger-key"},domain:{type:String},includeDeviceClass:{type:String,attribute:"include-device-class"},label:{type:String},_saving:{state:!0},_error:{state:!0}}}constructor(){super(),this.entryId="",this.optionKey="",this.chargerIndex=-1,this.chargerKey="",this.domain="",this.includeDeviceClass="",this.label="",this._saving=!1,this._error=""}static get styles(){return a`
            :host { display: block; padding: 6px 0; }
            .picker-row { display: flex; align-items: center; gap: 8px; }
            .picker-label {
                font-size: 14px; font-weight: 500;
                color: var(--primary-text-color);
                min-width: 140px; flex-shrink: 0;
            }
            ha-entity-picker { flex: 1; min-width: 0; }
            .status {
                font-size: 11px; color: var(--secondary-text-color);
                margin-top: 3px;
            }
            .status.error { color: var(--error-color, #d33); }
            .status.ok { color: var(--success-color, #8DC892); }
        `}_entry(){return this.hass&&this.entryId&&(this.hass.config_entries||[]).find(e=>e.entry_id===this.entryId)||null}_currentValue(){const e=this._entry();if(!e||!e.options)return"";if(this.chargerKey&&this.chargerIndex>=0){const t=e.options.ev_chargers||[];return t[this.chargerIndex]?.[this.chargerKey]||""}return e.options[this.optionKey]||""}async _onChange(e){const t=e.detail?.value||"",i=this._entry();if(!i)return void(this._error="config entry not found");let s;if(this._saving=!0,this._error="",this.chargerKey&&this.chargerIndex>=0){const e=(i.options?.ev_chargers||[]).map(e=>({...e}));e[this.chargerIndex]||(e[this.chargerIndex]={}),e[this.chargerIndex][this.chargerKey]=t,s={...i.options,ev_chargers:e}}else s={...i.options,[this.optionKey]:t};try{await this.hass.callWS({type:"config_entries/update",entry_id:this.entryId,options:s}),this._saving=!1}catch(e){this._saving=!1,this._error=e?.message||String(e),console.error("[sem-entity-picker] save failed",e)}}render(){if(!this.hass)return q;const e=this._currentValue();return this.domain&&this.domain,this.includeDeviceClass&&this.includeDeviceClass,W`
            <div class="picker-row">
                ${this.label?W`<span class="picker-label">${this.label}</span>`:q}
                <ha-entity-picker
                    .hass=${this.hass}
                    .value=${e}
                    .includeDomains=${this.domain?[this.domain]:void 0}
                    .includeDeviceClasses=${this.includeDeviceClass?[this.includeDeviceClass]:void 0}
                    .allowCustomEntity=${!1}
                    @value-changed=${this._onChange}>
                </ha-entity-picker>
            </div>
            ${this._error?W`<div class="status error">⚠ ${this._error}</div>`:this._saving?W`<div class="status">saving…</div>`:q}
        `}}customElements.get("sem-entity-picker")||customElements.define("sem-entity-picker",Yt);const Xt=[{id:"overview",icon:"mdi:check-decagram",color:"#8DC892",docs:"https://github.com/traktore-org/sem-community/blob/main/docs/README.md",titleKey:"config_section_overview",subtitleFn:e=>e._overviewSubtitle(),expanded:!0},{id:"ev_chargers",docs:"https://github.com/traktore-org/sem-community/blob/main/docs/EV_CHARGING_LOGIC.md#the-five-charge-modes",icon:"mdi:ev-station",color:"#5BC8D8",titleKey:"config_section_ev_chargers",subtitleFn:e=>e._evChargersSubtitle()},{id:"battery_zones",docs:"https://github.com/traktore-org/sem-community/blob/main/docs/SETUP_GUIDE.md#6-soc-zone-strategy",icon:"mdi:battery-charging-medium",color:"#4db6ac",titleKey:"config_section_battery_zones",subtitleFn:e=>e._batteryZonesSubtitle()},{id:"tariff",docs:"https://github.com/traktore-org/sem-community/blob/main/docs/SETUP_GUIDE.md#tariff-and-pricing-settings",icon:"mdi:cash-multiple",color:"#96CAEE",titleKey:"config_section_tariff",subtitleFn:e=>e._tariffSubtitle()},{id:"heat_pump",docs:"https://github.com/traktore-org/sem-community/blob/main/docs/SETUP_GUIDE.md#10-heat-pump-and-hot-water",icon:"mdi:heat-pump",color:"#4db6ac",titleKey:"config_section_heat_pump",subtitleFn:e=>e._heatPumpSubtitle()},{id:"hot_water",docs:"https://github.com/traktore-org/sem-community/blob/main/docs/SETUP_GUIDE.md#hot-water-boiler-separate-from-heat-pump",icon:"mdi:water-boiler",color:"#5BC8D8",titleKey:"config_section_hot_water",subtitleFn:e=>e._hotWaterSubtitle()},{id:"battery_scheduler",docs:"https://github.com/traktore-org/sem-community/blob/main/docs/SETUP_GUIDE.md#9-battery-charge-scheduler",icon:"mdi:calendar-clock",color:"#f06292",titleKey:"config_section_battery_scheduler",subtitleFn:()=>""},{id:"load_management",docs:"https://github.com/traktore-org/sem-community/blob/main/docs/LOAD_PRIORITY.md#what-it-does",icon:"mdi:flash-alert",color:"#ff9800",titleKey:"config_section_load_management",subtitleFn:e=>e._loadMgmtSubtitle()},{id:"forecast",docs:"https://github.com/traktore-org/sem-community/blob/main/docs/SETUP_GUIDE.md#forecast-settings",icon:"mdi:weather-partly-cloudy",color:"#ff9800",titleKey:"config_section_forecast",subtitleFn:e=>e._forecastSubtitle()},{id:"pv_strings",docs:"https://github.com/traktore-org/sem-community/blob/main/docs/PV_STRINGS.md#what-you-get",icon:"mdi:solar-panel",color:"#ff9800",titleKey:"config_section_pv_strings",subtitleFn:e=>e._pvStringsSubtitle()},{id:"notifications",docs:"https://github.com/traktore-org/sem-community/blob/main/docs/SETUP_GUIDE.md#notification-settings",icon:"mdi:bell-outline",color:"#96CAEE",titleKey:"config_section_notifications",subtitleFn:()=>""},{id:"advanced",docs:"https://github.com/traktore-org/sem-community/blob/main/docs/SETUP_GUIDE.md#advanced-settings",icon:"mdi:cog-outline",color:"#888",titleKey:"config_section_advanced",subtitleFn:()=>""}],Zt=["binary_sensor.sem_heat_pump_registered","sensor.sem_heat_pump_mode","sensor.sem_heat_pump_sg_ready_state","number.sem_heat_pump_boost_offset","sensor.sem_tariff_provider","sensor.sem_tariff_price_level","sensor.sem_tariff_current_import_rate","sensor.sem_forecast_source","sensor.sem_load_management_status","sensor.sem_battery_soc","sensor.sem_battery_status","number.sem_battery_priority_soc","number.sem_battery_buffer_soc","number.sem_battery_auto_start_soc","number.sem_battery_assist_min_surplus","number.sem_battery_assist_max_power","number.sem_cheap_price_threshold","number.sem_expensive_price_threshold","number.sem_minimum_solar_power","number.sem_update_interval","number.sem_ev_enable_delay_seconds","number.sem_ev_disable_delay_seconds","number.sem_regulation_offset","switch.sem_observer_mode","sensor.sem_diag_grid_sign","sensor.sem_diag_battery_sign"],Jt=new Set(["battery_soc_sensor","heat_pump_relay1_entity","heat_pump_relay2_entity","heat_pump_climate_entity","heat_pump_power_sensor","heat_pump_temperature_sensor","heat_pump_invert_sg_ready","hot_water_entity","hot_water_power_sensor","hot_water_temperature_sensor","battery_force_discharge_control_entity","battery_strategy_control_entity","battery_discharge_control_entity","battery_discharge_protection_enabled","battery_setpoint_bidirectional"]);$e("sem-config-card",class extends ke{static get watchedEntities(){return Zt}static get properties(){return{...super.properties,_showHelp:{state:!0},_entryId:{state:!0},_saveStatus:{state:!0},_signBusy:{state:!0},_signMsg:{state:!0},_battSignBusy:{state:!0},_battSignMsg:{state:!0},_pending:{state:!0},_applying:{state:!0},_pendingRemove:{state:!0},_chargerBusy:{state:!0},_staged:{state:!0},_secApplying:{state:!0},_helpOpen:{state:!0}}}constructor(){super(),this._collapsed={overview:!1,ev_chargers:!0,battery_zones:!0,tariff:!0,heat_pump:!0,hot_water:!0,battery_scheduler:!0,load_management:!0,forecast:!0,pv_strings:!0,notifications:!0,advanced:!0},this._showHelp=!1,this._entryId="",this._saveStatus={},this._statusTimers=new Set,this._signBusy=!1,this._signMsg="",this._battSignBusy=!1,this._battSignMsg="",this._pending={},this._applying=!1,this._pendingRemove="",this._chargerBusy=!1,this._staged={},this._secApplying="",this._helpOpen={},this._secOf={},this._sec=null}disconnectedCallback(){super.disconnectedCallback();for(const e of this._statusTimers)clearTimeout(e);this._statusTimers.clear()}setConfig(e){super.setConfig(e),this._prefix=e.entity_prefix||"sensor.sem_",e.entry_id&&(this._entryId=e.entry_id)}async _ensureEntryId(){if(this._entryId||!this._hass)return this._entryId;try{const e=await this._hass.callWS({type:"config_entries/get",domain:"solar_energy_management"});Array.isArray(e)&&e.length>0&&(this._entryId=e[0].entry_id,this.requestUpdate())}catch(e){console.warn("[sem-config-card] entry lookup failed",e)}return this._entryId}async _saveOption(e,t,i){const s=await this._ensureEntryId();this._saveStatus={...this._saveStatus,[i||e]:"saving"};try{await this._hass.callService("solar_energy_management","set_option",{options:{[e]:t},...s?{entry_id:s}:{}}),this._saveStatus={...this._saveStatus,[i||e]:"ok"},this._options={...this._options,[e]:t},this.requestUpdate();const r=setTimeout(()=>{this._statusTimers.delete(r),this._saveStatus={...this._saveStatus},delete this._saveStatus[i||e],this.requestUpdate()},1200);this._statusTimers.add(r)}catch(t){console.error("[sem-config-card] save failed",e,t),this._saveStatus={...this._saveStatus,[i||e]:t?.message||"save failed"},this.requestUpdate()}}_options={};async _refreshOptions(){if(this._hass)try{const e=await this._hass.callService("solar_energy_management","get_config",{},void 0,void 0,!0),t=e?.response?.config||{};this._options=t,e?.response?.entry_id&&!this._entryId&&(this._entryId=e.response.entry_id),this.requestUpdate()}catch(e){console.warn("[sem-config-card] get_config failed",e)}}connectedCallback(){super.connectedCallback(),this._hass?this._ensureEntryId().then(()=>this._refreshOptions()):this._needsEntryLookup=!0}set hass(e){super.hass=e,this._needsEntryLookup&&e&&(this._needsEntryLookup=!1,this._ensureEntryId().then(()=>this._refreshOptions()))}get hass(){return super.hass}_toggleHelp(){this._showHelp=!this._showHelp}_toggleSection(e){this._collapsed={...this._collapsed,[e]:!this._collapsed[e]},this.requestUpdate()}_val(e){const t=this._hass?.states[`${this._prefix}${e}`];return t&&"unavailable"!==t.state&&"unknown"!==t.state?t.state:""}_bin(e){return"on"===this._hass?.states[`binary_sensor.sem_${e}`]?.state}_valNum(e,t=0){const i=this._hass?.states[`${this._prefix}${e}`];if(!i||"unavailable"===i.state||"unknown"===i.state)return t;const s=parseFloat(i.state);return Number.isNaN(s)?t:s}_switchOn(e){const t=this._hass?.states[`switch.sem_${e}`];return"on"===t?.state}async _toggleSwitch(e){const t=this._hass?.states[e];t&&await this._hass.callService("switch","on"===t.state?"turn_off":"turn_on",{entity_id:e})}async _stepNumber(e,t){const i=this._hass?.states[e];if(!i)return;const s=parseFloat(i.attributes.step)||1,r=parseFloat(i.attributes.min)??0,a=parseFloat(i.attributes.max)??100;let o=(parseFloat(i.state)||0)+t*s;o=Math.max(r,Math.min(a,o)),await this._hass.callService("number","set_value",{entity_id:e,value:o})}async _selectOption(e,t){await this._hass.callService("select","select_option",{entity_id:e,option:t})}async _setNumber(e,t){const i=this._hass?.states[e];if(!i)return;const s=parseFloat(i.attributes.min),r=parseFloat(i.attributes.max);let a=t;Number.isNaN(s)||(a=Math.max(s,a)),Number.isNaN(r)||(a=Math.min(r,a)),await this._hass.callService("number","set_value",{entity_id:e,value:a})}_num(e,t=null){const i=this._hass?.states[e];if(!i||"unavailable"===i.state||"unknown"===i.state)return t;const s=parseFloat(i.state);return Number.isNaN(s)?t:s}_overviewSubtitle(){const e=this._chargersList().length,t=this._bin("heat_pump_registered"),i=[];return i.push(`${e} ${this._t("config_subtitle_chargers")}`),t&&i.push(this._t("config_subtitle_heatpump_on")),i.join(" · ")}_evChargersSubtitle(){return`${this._chargersList().length}`}_batteryZonesSubtitle(){const e=this._valNum("battery_soc");return`${this._t("soc")} ${e.toFixed(0)}%`}_tariffSubtitle(){const e=this._val("tariff_provider")||"—",t=this._val("tariff_price_level")||"";return t?`${e} · ${this._t(t.toLowerCase())||t}`:e}_heatPumpSubtitle(){return this._bin("heat_pump_registered")?this._t("configured"):this._t("not_configured")}_hotWaterSubtitle(){return(this._options||{}).hot_water_entity?this._t("configured"):this._t("not_configured")}_loadMgmtSubtitle(){return this._val("load_management_status")||""}_forecastSubtitle(){const e=this._forecastProviderLabel(this._val("forecast_source"));return e||this._t("not_configured")}_chargersList(){const e=new Set;for(const t of Object.keys(this._hass?.states||{})){const i=t.match(/^number\.sem_charger_(.+)_minimum_current$/);i&&e.add(i[1])}return Array.from(e).sort()}_openHaSettings(e=""){window.history.pushState(null,"","/config/integrations/integration/solar_energy_management"),window.dispatchEvent(new PopStateEvent("popstate"))}_renderStepper(e,t,i,s){return this._renderZoneKnob(e,t,i,s)}_renderToggle(e,t,i,s){const r=this._hass?.states[e];if(!r)return q;this._reg(e);const a=this._isDirty(e),o="on"===String(this._stagedVal(e,r.state));return W`
            <div class="stepper-cell ${a?"dirty":""}">
                <div class="toggle-row">
                    <span class="toggle-label">${this._t(t)}${a?W`<span class="dirty-dot">●</span>`:q}${this._helpBtn(s)}</span>
                    <div class="toggle-track ${o?"on":""}"
                         @click=${()=>this._stage(e,"switch",o?"off":"on")}>
                        <div class="toggle-thumb"></div>
                    </div>
                </div>
                ${this._helpBlock(s)}
            </div>
        `}_renderSelect(e,t,i,s){const r=this._hass?.states[e];if(!r)return q;this._reg(e);const a=this._isDirty(e),o=String(this._stagedVal(e,r.state)),n=r.attributes.options||[];return W`
            <div class="stepper-cell ${a?"dirty":""}">
                <div class="ctrl-row">
                    <span class="ctrl-label">${this._t(t)}${a?W`<span class="dirty-dot">●</span>`:q}${this._helpBtn(s)}</span>
                    <select class="sem-select" .value=${o}
                            @change=${t=>this._stage(e,"select",t.target.value)}>
                        ${n.map(e=>W`<option value="${e}" ?selected=${e===o}>${this._t(e.toLowerCase())||e}</option>`)}
                    </select>
                </div>
                ${this._helpBlock(s)}
            </div>
        `}_renderHaSettingsButton(e){return W`
            <button class="ha-settings-btn" @click=${()=>this._openHaSettings()}>
                <ha-icon icon="mdi:cog-outline" style="--mdc-icon-size:14px"></ha-icon>
                ${this._t(e)}
            </button>
        `}_setupItems(){const e=this._options||{};return[{key:"energy",labelKey:"config_overview_energy_dashboard",icon:"mdi:flash",color:"#ff9800",sectionId:"overview",done:!!this._hass?.states["sensor.sem_charging_state"]},{key:"ev",labelKey:"config_overview_chargers",icon:"mdi:ev-station",color:"#5BC8D8",sectionId:"ev_chargers",done:this._chargersList().length>0},{key:"hp",labelKey:"heat_pump_title",icon:"mdi:heat-pump",color:"#4db6ac",sectionId:"heat_pump",done:this._bin("heat_pump_registered")},{key:"hw",labelKey:"config_section_hot_water",icon:"mdi:water-boiler",color:"#5BC8D8",sectionId:"hot_water",done:!!e.hot_water_entity}]}_openSection(e){this._collapsed={...this._collapsed,[e]:!1},this.requestUpdate()}_renderOverview(e){const t=this._setupItems(),i=t.filter(e=>e.done).length,s=t.length,r=i===s,a=s?Math.round(i/s*100):100;return W`
            <div class="setup-progress">
                <div class="setup-progress-top">
                    <span class="setup-progress-label">
                        ${r?this._t("config_setup_done"):this._t("config_setup_progress").replace(/\{done\}/g,String(i)).replace(/\{total\}/g,String(s))}
                    </span>
                    <span class="setup-progress-pct">${a}%</span>
                </div>
                <div class="setup-progress-bar">
                    <div class="setup-progress-fill ${r?"done":""}" style=${`width:${a}%`}></div>
                </div>
            </div>
            <div class="chips">
                ${t.map(e=>W`
                    <div class="chip ${e.done?"":"chip-todo"}"
                        @click=${e.done?void 0:()=>this._openSection(e.sectionId)}>
                        <ha-icon icon="${e.icon}" style="--mdc-icon-size:16px;color:${e.color}"></ha-icon>
                        <div class="chip-label">${this._t(e.labelKey)}</div>
                        <div class="chip-value ${e.done?"c-ok":"c-warn"}">
                            ${e.done?"✓":this._t("config_setup_action")}
                        </div>
                    </div>`)}
            </div>
            <div class="overview-help">${this._t("config_overview_help")}</div>
            <div class="overview-actions">
                ${this._renderHaSettingsButton("config_open_ha_settings")}
            </div>
        `}_renderEvChargers(e){const t=this._options||{},i=t.ev_chargers||[],s=this._chargersList();if(0===i.length&&0===s.length)return W`
                <div class="empty-state">
                    <ha-icon icon="mdi:ev-station-outline" style="--mdc-icon-size:32px;color:#5BC8D8;opacity:0.7"></ha-icon>
                    <div class="empty-title">${this._t("config_ev_no_chargers")}</div>
                    <button class="add-charger-btn" ?disabled=${this._chargerBusy} @click=${()=>this._addCharger()}>
                        <ha-icon icon="mdi:plus" style="--mdc-icon-size:16px"></ha-icon>
                        ${this._t("config_ev_add_charger")}
                    </button>
                </div>
            `;const r=i.length?i:s.map(e=>({}));return W`
            ${r.map((i,r)=>{const a=i.id||s[r];return a?W`
                <div class="charger-block">
                    <div class="charger-block-title">
                        <ha-icon icon="mdi:ev-station" style="--mdc-icon-size:18px;color:#5BC8D8"></ha-icon>
                        <span style="flex:1">${this._chargerFriendlyName(a)}</span>
                        ${this._pendingRemove===a?q:W`
                            <button class="charger-remove-x" title="${this._t("config_ev_remove")}"
                                ?disabled=${this._chargerBusy}
                                @click=${()=>{this._chargerBusy||(this._pendingRemove=a,this.requestUpdate())}}>✕</button>`}
                    </div>
                    ${this._pendingRemove===a?W`
                        <div class="charger-remove-confirm">
                            <span>${this._t("config_ev_remove_confirm")}</span>
                            <button class="charger-remove-cancel" @click=${()=>{this._pendingRemove="",this.requestUpdate()}}>${this._t("config_discard")}</button>
                            <button class="charger-remove-go" @click=${()=>this._removeCharger(a)}>${this._t("config_ev_remove")}</button>
                        </div>`:q}
                    ${this._renderPickerNested(r,a,"ev_connected_sensor","config_ev_connected_sensor","binary_sensor",null,t,"config_help_ev_connected_sensor")}
                    ${this._renderPickerNested(r,a,"ev_charging_power_sensor","config_ev_charging_power","sensor","power",t,"config_help_ev_charging_power")}
                    ${this._renderPickerNested(r,a,"ev_current_control_entity","config_ev_current_control","number",null,t,"config_help_ev_current_control")}
                    ${this._renderPickerNested(r,a,"vehicle_soc_entity","config_ev_vehicle_soc","sensor",null,t,"config_help_ev_vehicle_soc")}
                    ${this._renderTargetTypeSelectNested(r,a,i,t)}
                    ${""}
                    <div class="stepper-pair">
                        ${this._renderStepper(`number.sem_charger_${a}_minimum_current`,"min_amps",e,"tile_help_min_amps")}
                        ${this._renderStepper(`number.sem_charger_${a}_ev_battery_capacity_kwh`,"capacity_kwh",e,"tile_help_capacity")}
                    </div>
                    ${""}
                    ${""}
                    ${"soc"===i.ev_target_type?W`
                        <div class="stepper-pair">
                            ${this._renderStepper(`number.sem_charger_${a}_target_soc`,"config_ev_target_soc",e,null)}
                            ${this._renderStepper(`number.sem_charger_${a}_target_soc_max`,"config_ev_target_soc_max",e,null)}
                        </div>`:W`
                        <div class="stepper-pair">
                            ${this._renderStepper(`number.sem_charger_${a}_daily_ev_target`,"config_ev_daily_target",e,null)}
                            ${this._renderStepper(`number.sem_charger_${a}_daily_ev_target_max`,"config_ev_daily_target_max",e,null)}
                        </div>`}
                    <div class="stepper-pair">
                        ${this._renderStepper(`number.sem_charger_${a}_ev_kwh_per_100km`,"config_ev_kwh_per_100km",e,null)}
                        ${this._renderStepper(`number.sem_charger_${a}_ev_phases`,"config_ev_phases",e,null)}
                    </div>
                </div>
            `:q})}
            <div class="section-footer">
                <button class="add-charger-btn" ?disabled=${this._chargerBusy} @click=${()=>this._addCharger()}>
                    <ha-icon icon="mdi:plus" style="--mdc-icon-size:16px"></ha-icon>
                    ${this._t("config_ev_add_charger")}
                </button>
            </div>
        `}_chargerFriendlyName(e){return(this._hass?.states[`number.sem_charger_${e}_minimum_current`]?.attributes?.friendly_name||e).replace(/\s+Min Amps$/i,"")}_renderZoneKnob(e,t,i,s){const r=this._hass?.states[e];if(!r)return q;this._reg(e);const a=parseFloat(r.state)||0,o=this._isDirty(e),n=Number(this._stagedVal(e,a)),l=parseFloat(r.attributes.min),c=parseFloat(r.attributes.max),d=Number.isNaN(l)?0:l,p=Number.isNaN(c)?100:c,h=parseFloat(r.attributes.step)||1,_=r.attributes.unit_of_measurement||"",g=h<1?1:0,u=p>d?Math.round((n-d)/(p-d)*100):0,f=t=>{const i=Math.max(d,Math.min(p,n+t*h));this._stage(e,"number",i)};return W`
            <div class="zone-knob ${o?"dirty":""}">
                <div class="zone-knob-top">
                    <span class="zone-knob-label">${this._t(t)}${this._helpBtn(s)}</span>
                    <span class="zone-chip">${o?W`<span class="dirty-dot">●</span>`:q}${n.toFixed(g)}${_?" "+_:""}</span>
                </div>
                <div class="zone-knob-slider">
                    <button class="zone-mini" @click=${()=>f(-1)}>−</button>
                    <input type="range" class="zone-range"
                        min=${d} max=${p} step=${h} .value=${String(n)}
                        style=${`--fill:${u}%`}
                        @change=${t=>this._stage(e,"number",parseFloat(t.target.value))} />
                    <button class="zone-mini" @click=${()=>f(1)}>+</button>
                </div>
                ${this._helpBlock(s,r.attributes.sem_default,_,e,"number")}
            </div>
        `}_renderSocZoneStrip(e){const t=this._num("number.sem_battery_priority_soc"),i=this._num("number.sem_battery_buffer_soc"),s=this._num("number.sem_battery_auto_start_soc");if(null==t||null==i||null==s)return q;const r=this._num("sensor.sem_battery_soc"),a=e=>Math.max(0,Math.min(100,e));return W`
            <div class="soc-strip">
                <div class="soc-bar">
                    <div class="soc-zone" style=${`width:${a(t)}%;background:#e57373`}></div>
                    <div class="soc-zone" style=${`width:${a(i-t)}%;background:#ffb74d`}></div>
                    <div class="soc-zone" style=${`width:${a(s-i)}%;background:#81c784`}></div>
                    <div class="soc-zone" style=${`width:${a(100-s)}%;background:#64b5f6`}></div>
                    ${null!=r?W`<div class="soc-now" style=${`left:${a(r)}%`} title="SOC ${r}%"></div>`:q}
                    <div class="soc-tick" style=${`left:${a(t)}%`}><span>${t}</span></div>
                    <div class="soc-tick" style=${`left:${a(i)}%`}><span>${i}</span></div>
                    <div class="soc-tick" style=${`left:${a(s)}%`}><span>${s}</span></div>
                </div>
                <div class="soc-legend">
                    <span><i style="background:#e57373"></i>${this._t("zone_legend_reserve")}</span>
                    <span><i style="background:#ffb74d"></i>${this._t("zone_legend_buffer")}</span>
                    <span><i style="background:#81c784"></i>${this._t("zone_legend_assist")}</span>
                    <span><i style="background:#64b5f6"></i>${this._t("zone_legend_surplus")}</span>
                </div>
            </div>
        `}_renderBatteryZones(e){const t=this._options||{};return W`
            ${this._renderSocZoneStrip(e)}
            ${""}
            ${this._renderPicker("battery_soc_sensor","config_battery_soc_sensor","sensor",null,t,"config_help_battery_soc_sensor")}
            ${""}
            ${this._renderPicker("battery_power_sensor","config_battery_power_sensor","sensor","power",t,"config_help_battery_power_sensor")}
            ${this._renderPicker("battery_cycles_sensor","config_battery_cycles_sensor","sensor",null,t,"config_help_battery_cycles_sensor")}
            ${this._renderZoneKnob("number.sem_battery_priority_soc","priority_soc",e,"zone_help_priority")}
            ${this._renderZoneKnob("number.sem_battery_buffer_soc","buffer_soc",e,"zone_help_buffer")}
            ${this._renderZoneKnob("number.sem_battery_auto_start_soc","auto_start_soc",e,"zone_help_autostart")}
            ${this._renderZoneKnob("number.sem_battery_assist_min_surplus","assist_min_surplus",e,"zone_help_assist_min_surplus")}
            ${this._renderZoneKnob("number.sem_battery_assist_max_power","assist_max_power",e,"zone_help_assist_max_power")}
            ${""}
            <div style="margin-top:6px;border-top:1px solid ${e.surfaceBorder};padding-top:4px"></div>
            ${this._renderOptionToggle("battery_discharge_protection_enabled","config_batt_protection",t,"config_help_batt_protection",!0)}
            ${this._renderZoneKnob("number.sem_battery_max_discharge_power","battery_max_discharge_power",e,"config_help_batt_max_discharge")}
            ${this._renderPicker("battery_discharge_control_entity","config_batt_discharge_entity","number",null,t,"config_help_batt_discharge_entity")}
        `}_renderTariff(e){const t=this._options||{},i=this._hass?.states["sensor.sem_tariff_current_import_rate"],s=i?i.state:"—",r=i?.attributes?.unit_of_measurement||"",a=this._hass?.config?.currency||"EUR",o=[{value:"static",label:this._t("config_tariff_mode_static")},{value:"dynamic",label:this._t("config_tariff_mode_dynamic")},{value:"calendar",label:this._t("config_tariff_mode_calendar")}],n=[{value:"percentile",label:this._t("config_tariff_class_percentile")},{value:"static",label:this._t("config_tariff_class_static")}],l=t.tariff_mode||"static";return W`
            <div class="readonly-row tariff-rate-row">
                <ha-icon icon="mdi:flash" style="--mdc-icon-size:18px;color:#ff9800"></ha-icon>
                <span class="ctrl-label" style="flex:1">${this._t("current_electricity_price")}</span>
                <span class="readonly-value tariff-rate-value">${s} ${r}</span>
            </div>
            ${this._renderOptionSelect("tariff_mode","config_tariff_mode",o,t,"config_help_tariff_mode","static")}
            ${"dynamic"===l?W`
                ${this._renderPicker("dynamic_tariff_entity","config_dynamic_tariff_entity","sensor",null,t,"config_help_dynamic_tariff_entity")}
                ${this._renderPicker("dynamic_forecast_entity","config_dynamic_forecast_entity","sensor",null,t,"config_help_dynamic_forecast_entity")}
                ${this._renderPicker("dynamic_feedin_entity","config_dynamic_feedin_entity","sensor",null,t,"config_help_dynamic_feedin_entity")}
                ${this._renderOptionSelect("tariff_classification_mode","config_tariff_class_mode",n,t,"config_help_tariff_class_mode","percentile")}
            `:q}
            <div class="stepper-pair">
                ${this._renderStepper("number.sem_cheap_price_threshold","cheap_threshold",e,"setting_help_cheap_threshold")}
                ${this._renderStepper("number.sem_expensive_price_threshold","expensive_threshold",e,"setting_help_expensive_threshold")}
            </div>
            ${""}
            ${this._renderOptionNumberInput("electricity_import_rate","config_import_rate",{min:0,max:1e4,step:.001,unit:`${a}/kWh`,default:.3387},t,"config_help_import_rate")}
            ${this._renderOptionNumberInput("electricity_off_peak_rate","config_off_peak_rate",{min:0,max:1e4,step:.001,unit:`${a}/kWh`,default:.3387},t,"config_help_off_peak_rate")}
            ${this._renderOptionNumberInput("electricity_export_rate","config_export_rate",{min:0,max:1e4,step:.001,unit:`${a}/kWh`,default:.075},t,"config_help_export_rate")}
            ${this._renderOptionNumberInput("demand_charge_rate","config_demand_charge_rate",{min:0,max:1e5,step:.01,unit:`${a}/kW/Mt`,default:4.32},t,"config_help_demand_charge_rate")}
            ${this._renderPicker("grid_import_power_entity","config_grid_import_entity","sensor","power",t,"config_help_grid_import_entity")}
            ${this._renderPicker("grid_export_power_entity","config_grid_export_entity","sensor","power",t,"config_help_grid_export_entity")}
            ${""}
            ${this._renderPicker("solar_production_sensor","config_solar_production_sensor","sensor","power",t,"config_help_solar_production_sensor")}
            ${this._hasBattery()?W`
                <div class="readonly-row" style="margin-top:6px;border-top:1px solid ${e.surfaceBorder};padding-top:8px">
                    <span class="ctrl-label" style="font-weight:600">${this._t("config_battery_control")}</span>
                </div>
                ${(()=>{const e=this._batteryCount();return e>1?W`${Array.from({length:e},(i,s)=>W`
                            ${this._renderBatteryDischargePicker(s,e,t)}
                            ${this._renderBatteryStrategyPicker(s,e,t)}`)}`:W`
                        ${this._renderPicker("battery_force_discharge_control_entity","config_force_discharge_entity","number",null,t,"config_help_force_discharge_entity")}
                        ${this._renderPicker("battery_strategy_control_entity","config_strategy_entity","select",null,t,"config_help_strategy_entity")}`})()}
                ${this._renderOptionToggle("battery_setpoint_bidirectional","config_battery_bidirectional",t,"config_help_battery_bidirectional",!1)}
            `:q}
            ${""}
        `}_renderHeatPump(e){const t=this._bin("heat_pump_registered"),i=this._options||{},s=t?W`
            <div class="hp-status">
                <div class="readonly-row">
                    <span class="ctrl-label">${this._t("heat_pump_mode")}</span>
                    <span class="readonly-value">${this._val("heat_pump_mode")||"—"}</span>
                </div>
                <div class="readonly-row">
                    <span class="ctrl-label">${this._t("heat_pump_sg_ready_state")}</span>
                    <span class="readonly-value">${this._val("heat_pump_sg_ready_state")||"—"}</span>
                </div>
            </div>
        `:W`
            <div class="setup-intro">
                ${this._t("config_heat_pump_intro")}
            </div>
        `;return W`
            ${s}
            <div class="hp-form">
                ${this._renderPicker("heat_pump_relay1_entity","config_hp_relay1",["switch","input_boolean"],null,i,"config_help_hp_relay")}
                ${this._renderPicker("heat_pump_relay2_entity","config_hp_relay2",["switch","input_boolean"],null,i,"config_help_hp_relay")}
                ${""}
                ${this._renderOptionToggle("heat_pump_invert_sg_ready","config_hp_invert_sg_ready",i,"config_help_hp_invert_sg_ready",!1)}
                ${this._renderPicker("heat_pump_climate_entity","config_hp_climate","climate",null,i,"config_help_hp_climate")}
                ${this._renderPicker("heat_pump_power_sensor","config_hp_power_sensor","sensor","power",i,"config_help_hp_power_sensor")}
                ${""}
                ${this._renderPicker("heat_pump_energy_sensor","config_hp_energy_sensor","sensor","energy",i,"config_help_hp_energy_sensor")}
                ${""}
                ${this._renderOptionNumberInput("heat_pump_rated_power","config_hp_rated_power",{min:100,max:3e4,step:50,unit:"W",default:2e3},i,"config_help_hp_rated_power")}
                ${""}
                ${this._renderPicker("heat_pump_temperature_sensor","config_hp_temperature_sensor","sensor","temperature",i,"config_help_hp_temperature_sensor")}
                ${""}
                ${this._renderPicker("vacation_mode_entity","config_vacation_entity",["binary_sensor","input_boolean","switch","calendar"],null,i,"config_help_vacation_entity")}
                ${t?this._renderStepper("number.sem_heat_pump_boost_offset","heat_pump_boost_offset",e,"config_help_hp_boost_offset"):this._renderOptionSlider("heat_pump_boost_offset","heat_pump_boost_offset",{min:0,max:10,step:.5,unit:"°C",default:2},i,"config_help_hp_boost_offset")}
                ${this._renderOptionSlider("heat_pump_max_setpoint","config_hp_max_setpoint",{min:30,max:80,step:1,unit:"°C",default:55},i,"config_help_hp_max_setpoint")}
                ${""}
            </div>
        `}_renderHotWater(e){const t=this._options||{},i=this._bin("hot_water_registered"),s=this._val("hot_water_current_temperature"),r=this._val("hot_water_solar_target"),a=this._val("hot_water_hours_since_legionella"),o=this._bin("hot_water_legionella_cycle_active"),n=this._val("hot_water_temperature_reading_path"),l=this._val("hot_water_temperature_safety_path"),c=this._val("hot_water_activation_path"),d=i?W`
            <div class="hp-status">
                <div class="readonly-row">
                    <span class="ctrl-label">${this._t("hot_water_current_temperature")}</span>
                    <span class="readonly-value">${s?`${parseFloat(s).toFixed(1)} °C`:"—"}</span>
                </div>
                <div class="readonly-row">
                    <span class="ctrl-label">${this._t("hot_water_solar_target")}</span>
                    <span class="readonly-value">${r?`${parseFloat(r).toFixed(0)} °C`:"—"}</span>
                </div>
                <div class="readonly-row">
                    <span class="ctrl-label">${this._t("hot_water_hours_since_legionella")}</span>
                    <span class="readonly-value">${o?this._t("hot_water_legionella_cycle_running"):a&&parseFloat(a)<999?`${parseFloat(a).toFixed(0)} h`:this._t("hot_water_legionella_never_run")}</span>
                </div>
                ${n?W`
                    <div class="readonly-row">
                        <span class="ctrl-label">${this._t("hot_water_temperature_reading_path")}</span>
                        <span class="readonly-value">${n}</span>
                    </div>
                `:q}
                ${l&&"uninitialized"!==l?W`
                    <div class="readonly-row">
                        <span class="ctrl-label">${this._t("hot_water_temperature_safety_path")}</span>
                        <span class="readonly-value">${l}</span>
                    </div>
                `:q}
                ${c&&"uninitialized"!==c?W`
                    <div class="readonly-row">
                        <span class="ctrl-label">${this._t("hot_water_activation_path")}</span>
                        <span class="readonly-value">${c}</span>
                    </div>
                `:q}
            </div>
        `:W`
            <div class="setup-intro">
                ${this._t("config_hot_water_intro")}
            </div>
        `;return W`
            ${d}
            <div class="hp-form">
                ${this._renderPicker("hot_water_entity","config_hw_entity",["switch","input_boolean","water_heater","climate"],null,t,"config_help_hw_entity")}
                ${this._renderPicker("hot_water_temperature_sensor","config_hw_temp_sensor","sensor","temperature",t,"config_help_hw_temp_sensor")}
                ${this._renderPicker("hot_water_power_sensor","config_hw_power_sensor","sensor","power",t,"config_help_hw_power_sensor")}
                ${""}
                ${this._renderPicker("hot_water_energy_sensor","config_hw_energy_sensor","sensor","energy",t,"config_help_hw_energy_sensor")}
                ${""}
                ${this._renderOptionNumberInput("hot_water_rated_power","config_hw_rated_power",{min:100,max:3e4,step:50,unit:"W",default:2500},t,"config_help_hw_rated_power")}
                ${this._renderStepper("number.sem_hot_water_solar_target","hot_water_solar_target",e,"config_help_hw_solar_target")}
                ${this._renderStepper("number.sem_hot_water_max_temperature","hot_water_max_temperature",e,"config_help_hw_max_temperature")}
                ${this._renderOptionSlider("hot_water_legionella_target","config_hw_legionella_target",{min:55,max:80,step:1,unit:"°C",default:65},t,"config_help_hw_legionella_target")}
                ${this._renderOptionSlider("hot_water_minimum_temperature","config_hw_min_temperature",{min:30,max:55,step:1,unit:"°C",default:40},t,"config_help_hw_min_temperature")}
                ${""}
            </div>
        `}async _saveChargerField(e,t,i,s,r,a){const o=(a.ev_chargers||[]).map(e=>({...e}));o[e]||(o[e]={}),!o[e].id&&t&&(o[e].id=t),o[e][i]=s,await this._saveOption("ev_chargers",o,r)}async _addCharger(){if(this._chargerBusy)return;const e=this._options.ev_chargers||[],t=new Set([...e.map(e=>e&&e.id).filter(Boolean),...this._chargersList()]);let i="ev_charger",s=1;for(;t.has(i);)i="ev_charger_"+s++;const r={id:i,name:`${this._t("config_ev_new_charger")} ${e.length+1}`,ev_min_current:6,max_charging_current:32,ev_surplus_priority:e.length+3};this._chargerBusy=!0,this.requestUpdate();try{await this._saveOption("ev_chargers",[r],"ev_chargers_add"),await this._refreshOptions()}finally{this._chargerBusy=!1,this.requestUpdate()}}async _removeCharger(e){if(!this._chargerBusy&&e){this._chargerBusy=!0,this._pendingRemove="",this.requestUpdate();try{await this._hass.callService("solar_energy_management","remove_charger",{charger_id:e}),await this._refreshOptions()}catch(e){console.error("[sem-config-card] remove_charger failed",e)}finally{this._chargerBusy=!1,this.requestUpdate()}}}_renderTargetTypeSelectNested(e,t,i,s){const r=i.ev_target_type||"kwh",a=!!i.vehicle_soc_entity,o=`ev_chargers.${e}.ev_target_type`,n=this._saveStatus[o];return W`
            <div class="stepper-cell">
                <div class="ctrl-row">
                    <span class="ctrl-label">${this._t("config_ev_target_type")}</span>
                    <select class="sem-select" .value=${r} @change=${i=>this._saveChargerField(e,t,"ev_target_type",i.target.value,o,s)}>
                        <option value="kwh" ?selected=${"soc"!==r}>
                            ${this._t("config_ev_target_type_kwh")}
                        </option>
                        <option value="soc" ?disabled=${!a}
                                            ?selected=${"soc"===r}>
                            ${this._t("config_ev_target_type_soc")}${a?"":" — "+this._t("config_ev_target_type_requires_sensor")}
                        </option>
                    </select>
                </div>
                ${"saving"===n?W`<div class="save-status">${this._t("config_saving")}…</div>`:q}
                ${"ok"===n?W`<div class="save-status ok">✓</div>`:q}
                ${this._showHelp?W`<div class="setting-help-text">${this._t("config_help_ev_target_type")}</div>`:q}
            </div>
        `}_renderPickerNested(e,t,i,s,r,a,o,n){const l=o.ev_chargers||[],c=l[e]?.[i]||"",d=`ev_chargers.${e}.${i}`,p=this._saveStatus[d],h=s=>this._saveChargerField(e,t,i,s,d,o);return W`
            <div class="picker-cell">
                <div class="picker-row">
                    <span class="picker-label">${this._t(s)}</span>
                    <ha-entity-picker
                        .hass=${this._hass}
                        .value=${c}
                        .includeDomains=${r?Array.isArray(r)?r:[r]:void 0}
                        .includeDeviceClasses=${a?[a]:void 0}
                        .allowCustomEntity=${!1}
                        @value-changed=${e=>h(e.detail?.value||"")}>
                    </ha-entity-picker>
                </div>
                ${"saving"===p?W`<div class="save-status">${this._t("config_saving")}…</div>`:q}
                ${"ok"===p?W`<div class="save-status ok">✓ ${this._t("config_saved")}</div>`:q}
                ${this._showHelp&&n?W`<div class="setting-help-text">${this._t(n)}</div>`:q}
            </div>
        `}_batteryCount(){if(!this._hass)return 0;const e=new Set;for(const t of Object.keys(this._hass.states)){const i=t.match(/^sensor\.sem_battery_(b\d+)_power$/);i&&e.add(i[1])}return e.size}_hasBattery(){return!!this._hass&&(this._batteryCount()>0||("sensor.sem_battery_soc"in this._hass.states||"sensor.sem_battery_power"in this._hass.states))}_renderBatteryStrategyPicker(e,t,i){const s="battery_strategy_entities",r=(Array.isArray(i[s])?i[s]:[])[e]||"",a=`${s}.${e}`,o=this._saveStatus[a];return W`
            <div class="picker-cell">
                <div class="picker-row">
                    <span class="picker-label">${this._t("config_strategy_entity")} — B${e+1}</span>
                    <ha-entity-picker
                        .hass=${this._hass}
                        .value=${r}
                        .includeDomains=${["select","input_select"]}
                        .allowCustomEntity=${!1}
                        @value-changed=${i=>this._saveListField(s,e,i.detail?.value||"",t)}>
                    </ha-entity-picker>
                </div>
                ${"saving"===o?W`<div class="save-status">${this._t("config_saving")}…</div>`:q}
                ${"ok"===o?W`<div class="save-status ok">✓ ${this._t("config_saved")}</div>`:q}
            </div>
        `}async _saveListField(e,t,i,s){const r=Array.isArray(this._options[e])?[...this._options[e]]:[];for(;r.length<s;)r.push(null);r[t]=i||null,await this._saveOption(e,r,`${e}.${t}`)}_renderBatteryDischargePicker(e,t,i){const s="battery_force_discharge_entities",r=(Array.isArray(i[s])?i[s]:[])[e]||"",a=`${s}.${e}`,o=this._saveStatus[a];return W`
            <div class="picker-cell">
                <div class="picker-row">
                    <span class="picker-label">${this._t("config_force_discharge_entity")} — B${e+1}</span>
                    <ha-entity-picker
                        .hass=${this._hass}
                        .value=${r}
                        .includeDomains=${["number","input_number"]}
                        .allowCustomEntity=${!1}
                        @value-changed=${i=>this._saveListField(s,e,i.detail?.value||"",t)}>
                    </ha-entity-picker>
                </div>
                ${"saving"===o?W`<div class="save-status">${this._t("config_saving")}…</div>`:q}
                ${"ok"===o?W`<div class="save-status ok">✓ ${this._t("config_saved")}</div>`:q}
            </div>
        `}_renderPicker(e,t,i,s,r,a){const o=this._saveStatus[e],n=Jt.has(e),l=n&&Object.prototype.hasOwnProperty.call(this._pending,e),c=l?this._pending[e]:r[e]||"",d=t=>{n?(this._pending={...this._pending,[e]:t||""},this.requestUpdate()):this._saveOption(e,t,e)};return W`
            <div class="picker-cell">
                <div class="picker-row">
                    <span class="picker-label">${this._t(t)}${l?W`<span class="pending-dot" title="${this._t("config_pending_hint")}">●</span>`:q}</span>
                    <ha-entity-picker
                        .hass=${this._hass}
                        .value=${c}
                        .includeDomains=${i?Array.isArray(i)?i:[i]:void 0}
                        .includeDeviceClasses=${s?[s]:void 0}
                        .allowCustomEntity=${!1}
                        @value-changed=${e=>d(e.detail?.value||"")}>
                    </ha-entity-picker>
                </div>
                ${"saving"===o?W`<div class="save-status">${this._t("config_saving")}…</div>`:q}
                ${"ok"===o?W`<div class="save-status ok">✓ ${this._t("config_saved")}</div>`:q}
                ${o&&"saving"!==o&&"ok"!==o?W`<div class="save-status err">⚠ ${o}</div>`:q}
                ${this._showHelp&&a?W`<div class="setting-help-text">${this._t(a)}</div>`:q}
            </div>
        `}async _applyPending(){if(!Object.keys(this._pending).length||this._applying)return;const e=await this._ensureEntryId();this._applying=!0;const t={...this._saveStatus};delete t._apply,this._saveStatus=t,this.requestUpdate();try{const t={...this._pending};await this._hass.callService("solar_energy_management","set_option",{options:t,...e?{entry_id:e}:{}}),this._options={...this._options,...t},this._pending={}}catch(e){console.error("[sem-config-card] apply failed",e),this._saveStatus={...this._saveStatus,_apply:e?.message||"apply failed"}}finally{this._applying=!1,this.requestUpdate()}}_discardPending(){this._pending={},this.requestUpdate()}_renderApplyBar(){const e=Object.keys(this._pending).length;if(!e&&!this._applying)return q;const t=this._saveStatus._apply;return W`
            <div class="apply-bar ${t?"apply-err":""}">
                <span class="apply-msg">
                    ${this._applying?W`<span class="apply-spin"></span>${this._t("config_applying")}`:t?W`⚠ ${t}`:this._t("config_pending_changes").replace(/\{n\}/g,String(e))}
                </span>
                ${this._applying?q:W`
                    <button class="apply-discard" @click=${()=>this._discardPending()}>${this._t("config_discard")}</button>
                    <button class="apply-btn" @click=${()=>this._applyPending()}>${this._t("config_apply")}</button>
                `}
            </div>
        `}_reg(e){this._sec&&(this._secOf[e]=this._sec)}_liveOf(e,t){if("option"===t){return(this._options||{})[e.slice(4)]}const i=this._hass?.states[e];if(i)return"number"===t?parseFloat(i.state):i.state}_stage(e,t,i){const s=this._liveOf(e,t),r="number"===t?Number(s)===Number(i):String(s)===String(i),a={...this._staged};r?delete a[e]:a[e]={kind:t,value:i},this._staged=a}_isDirty(e){return Object.prototype.hasOwnProperty.call(this._staged,e)}_stagedVal(e,t){const i=this._staged[e];return void 0===i?t:i.value}_sectionStaged(e){return Object.keys(this._staged).filter(t=>this._secOf[t]===e)}_revertSection(e){const t={...this._staged};this._sectionStaged(e).forEach(e=>delete t[e]),this._staged=t}async _applySection(e){const t=this._sectionStaged(e);if(t.length&&!this._secApplying){this._secApplying=e;try{const e={};for(const i of t){const t=this._staged[i];"option"===t.kind?e[i.slice(4)]=t.value:"number"===t.kind?await this._hass.callService("number","set_value",{entity_id:i,value:Number(t.value)}):"select"===t.kind?await this._hass.callService("select","select_option",{entity_id:i,option:String(t.value)}):"switch"===t.kind&&await this._hass.callService("switch","on"===t.value?"turn_on":"turn_off",{entity_id:i})}if(Object.keys(e).length){const t=await this._ensureEntryId();await this._hass.callService("solar_energy_management","set_option",{options:e,...t?{entry_id:t}:{}}),this._options={...this._options,...e}}const i={...this._staged};t.forEach(e=>delete i[e]),this._staged=i}catch(t){console.error("[sem-config-card] section apply failed",t),this._saveStatus={...this._saveStatus,["_sec_"+e]:t?.message||"apply failed"}}finally{this._secApplying="",this.requestUpdate()}}}_helpVisible(e){return!(!e||!this._showHelp&&!this._helpOpen[e])}_helpBtn(e){return e?W`<ha-icon class="row-help-btn ${this._helpOpen[e]?"on":""}"
            icon="mdi:information-outline" style="--mdc-icon-size:14px"
            @click=${t=>{t.stopPropagation(),this._helpOpen={...this._helpOpen,[e]:!this._helpOpen[e]}}}></ha-icon>`:q}_helpBlock(e,t,i,s,r){if(!this._helpVisible(e))return q;const a=null!=t&&""!==t,o=a&&s&&r;return W`<div class="setting-help-text">${this._t(e)}${a?W` <span class="help-default">${this._t("config_default_label")}: ${t}${i?" "+i:""}</span>`:q}${o?W` <button class="help-reset-btn" title="${this._t("config_reset_default")}"
                  @click=${e=>{e.stopPropagation(),this._stage(s,r,t)}}>↺ ${this._t("config_reset_default")}</button>`:q}</div>`}_renderOptionSelect(e,t,i,s,r,a){const o="opt:"+e;this._reg(o);const n=null!=s[e]?s[e]:a,l=this._isDirty(o),c=this._stagedVal(o,n);return W`
            <div class="stepper-cell ${l?"dirty":""}">
                <div class="ctrl-row">
                    <span class="ctrl-label">${this._t(t)}${l?W`<span class="dirty-dot">●</span>`:q}${this._helpBtn(r)}</span>
                    <select class="sem-select"
                            .value=${c}
                            @change=${e=>this._stage(o,"option",e.target.value)}>
                        ${i.map(e=>W`
                            <option value="${e.value}" ?selected=${e.value===c}>${e.label}</option>
                        `)}
                    </select>
                </div>
                ${this._helpBlock(r,a,void 0,o,"option")}
            </div>
        `}_renderOptionToggle(e,t,i,s,r){const a=Jt.has(e),o="opt:"+e;a||this._reg(o);const n=a&&Object.prototype.hasOwnProperty.call(this._pending,e),l=null!=i[e]?!!i[e]:!!r,c=n||!a&&this._isDirty(o),d=n?!!this._pending[e]:!a&&this._isDirty(o)?!!this._staged[o].value:l;return W`
            <div class="stepper-cell ${c?"dirty":""}">
                <div class="toggle-row">
                    <span class="toggle-label">${this._t(t)}${c?W`<span class="dirty-dot" title="${this._t("config_pending_hint")}">●</span>`:q}${this._helpBtn(s)}</span>
                    <div class="toggle-track ${d?"on":""}"
                         @click=${()=>{a?(this._pending={...this._pending,[e]:!d},this.requestUpdate()):this._stage(o,"option",!d)}}>
                        <div class="toggle-thumb"></div>
                    </div>
                </div>
                ${this._helpBlock(s)}
            </div>
        `}_renderOptionNumberInput(e,t,i,s,r){const a="opt:"+e;this._reg(a);const o=null!=s[e]?s[e]:i.default,n=this._isDirty(a),l=this._stagedVal(a,o),c=e=>{const t=parseFloat(e);if(Number.isNaN(t))return;const s=Math.max(i.min,Math.min(i.max,t));this._stage(a,"option",s)};return W`
            <div class="stepper-cell ${n?"dirty":""}">
                <div class="ctrl-row">
                    <span class="ctrl-label">${this._t(t)}${n?W`<span class="dirty-dot">●</span>`:q}${this._helpBtn(r)}</span>
                    <div class="num-input-wrap">
                        <input class="sem-num-input" type="number"
                               .value=${String(l)}
                               min=${i.min} max=${i.max} step=${i.step}
                               @change=${e=>c(e.target.value)}
                               @blur=${e=>c(e.target.value)}
                               @keydown=${e=>{"Enter"===e.key&&e.target.blur()}}>
                        ${i.unit?W`<span class="num-unit">${i.unit}</span>`:q}
                    </div>
                </div>
                ${this._helpBlock(r,i.default,i.unit,a,"option")}
            </div>
        `}_renderOptionSlider(e,t,i,s,r){const a="opt:"+e;this._reg(a);const o=parseFloat(null!=s[e]?s[e]:i.default)||0,n=this._isDirty(a),l=Number(this._stagedVal(a,o)),c=i.step<1?1:0,d=i.unit||"",p=i.max>i.min?Math.round((l-i.min)/(i.max-i.min)*100):0,h=e=>{const t=Math.min(i.max,Math.max(i.min,l+e*i.step));this._stage(a,"option",t)};return W`
            <div class="zone-knob ${n?"dirty":""}">
                <div class="zone-knob-top">
                    <span class="zone-knob-label">${this._t(t)}${this._helpBtn(r)}</span>
                    <span class="zone-chip">${n?W`<span class="dirty-dot">●</span>`:q}${l.toFixed(c)}${d?" "+d:""}</span>
                </div>
                <div class="zone-knob-slider">
                    <button class="zone-mini" @click=${()=>h(-1)}>−</button>
                    <input type="range" class="zone-range"
                        min=${i.min} max=${i.max} step=${i.step} .value=${String(l)}
                        style=${`--fill:${p}%`}
                        @change=${e=>this._stage(a,"option",parseFloat(e.target.value))} />
                    <button class="zone-mini" @click=${()=>h(1)}>+</button>
                </div>
                ${this._helpBlock(r,i.default,d,a,"option")}
            </div>
        `}_renderBatteryScheduler(e){const t=this._options||{};return W`
            <div class="setup-intro">${this._t("config_battery_scheduler_intro")}</div>
            ${this._renderOptionToggle("battery_charge_scheduler_enabled","config_bs_enabled",t,"config_help_bs_enabled",!1)}
            ${this._renderOptionNumberInput("battery_capacity_kwh","config_bs_capacity",{min:1,max:100,step:.5,unit:"kWh",default:10},t,"config_help_bs_capacity")}
            ${this._renderOptionNumberInput("battery_max_charge_power_w","config_bs_max_charge",{min:500,max:25e3,step:100,unit:"W",default:5e3},t,"config_help_bs_max_charge")}
            ${this._renderOptionSlider("battery_roundtrip_efficiency","config_bs_efficiency",{min:.7,max:.99,step:.01,unit:"",default:.92},t,"config_help_bs_efficiency")}
            ${this._renderOptionNumberInput("battery_cycle_cost","config_bs_cycle_cost",{min:0,max:.5,step:.001,unit:"EUR/kWh",default:.02},t,"config_help_bs_cycle_cost")}
            ${this._renderOptionSlider("battery_precharge_trigger_hour","config_bs_trigger_hour",{min:18,max:23,step:1,unit:"h",default:21},t,"config_help_bs_trigger_hour")}
            ${this._renderOptionSlider("battery_replan_interval_min","config_bs_replan_interval",{min:5,max:120,step:5,unit:"min",default:30},t,"config_help_bs_replan_interval")}
            ${this._renderOptionToggle("battery_prefer_consecutive_window","config_bs_block_mode",t,"config_help_bs_block_mode",!0)}
            ${this._renderOptionSlider("battery_max_target_soc","config_bs_max_target_soc",{min:50,max:100,step:5,unit:"%",default:95},t,"config_help_bs_max_target_soc")}
            ${this._renderOptionNumberInput("battery_min_deficit_kwh","config_bs_min_deficit",{min:.5,max:10,step:.5,unit:"kWh",default:2},t,"config_help_bs_min_deficit")}
            ${this._renderOptionSlider("battery_pessimism_weight","config_bs_pessimism",{min:0,max:1,step:.1,unit:"",default:.3},t,"config_help_bs_pessimism")}
            ${this._renderOptionToggle("battery_force_charge_negative_price","config_bs_force_neg",t,"config_help_bs_force_neg",!0)}
        `}_renderLoadManagement(e){const t=this._options||{};return W`
            <div class="readonly-row">
                <span class="ctrl-label">${this._t("load_management_status")}</span>
                <span class="readonly-value">${this._val("load_management_status")||"—"}</span>
            </div>
            ${this._renderOptionToggle("load_management_enabled","config_lm_enabled",t,"config_help_lm_enabled",!0)}
            ${this._renderOptionSlider("target_peak_limit","config_lm_target_peak",{min:1,max:15,step:.5,unit:"kW",default:5},t,"config_help_lm_target_peak")}
            ${this._renderOptionSlider("warning_peak_level","config_lm_warning_peak",{min:1,max:15,step:.5,unit:"kW",default:4.5},t,"config_help_lm_warning_peak")}
            ${this._renderOptionSlider("emergency_peak_level","config_lm_emergency_peak",{min:1,max:20,step:.5,unit:"kW",default:6},t,"config_help_lm_emergency_peak")}
        `}_renderForecast(e){const t=this._val("forecast_source")||"none",i="none"===t?this._t("none"):this._forecastProviderLabel(t);return W`
            <div class="readonly-row">
                <span class="ctrl-label">${this._t("forecast_source")}</span>
                <span class="readonly-value">${i}</span>
            </div>
            ${"none"===t?W`<div class="overview-help">${this._t("config_forecast_install_hint")}</div>`:q}
        `}_pvStrings(){const e=this._hass?.states||{},t=[];for(const i of Object.keys(e)){const s=i.match(/^sensor\.sem_pv_string_(pv\d+)_power$/);if(!s)continue;const r=e[i];t.push({slot:s[1],power:parseFloat(r.state),displayName:r.attributes?.string_name||s[1].toUpperCase()})}return t.sort((e,t)=>e.slot.localeCompare(t.slot,void 0,{numeric:!0})),t}_pvStringsSubtitle(){const e=this._pvStrings().length;return e?`${e} ${this._t("pv_strings_unit")||"strings"}`:""}_onPvNameInput(e,t){this._pvNameEdits={...this._pvNameEdits||{},[e]:t}}async _savePvNames(){const e={...this._options?.pv_string_names||{}},t=this._pvNameEdits||{};for(const[i,s]of Object.entries(t)){const t=(s||"").trim();t?e[i]=t:delete e[i]}await this._saveOption("pv_string_names",e,"pv_string_names"),this._pvNameEdits={}}_renderPvStrings(e){const t=this._pvStrings(),i=this._options?.pv_string_names||{},s=this._pvNameEdits||{},r=this._saveStatus?.pv_string_names;return W`
            <div class="setting-help-text">${this._t("config_pv_strings_help")}</div>
            ${t.map(e=>{const t=void 0!==s[e.slot]?s[e.slot]:i[e.slot]||"",r=Number.isFinite(e.power)?`${e.power.toFixed(0)} W`:"";return W`
                    <div class="pv-name-row">
                        <div class="pv-name-meta">
                            <span class="pv-name-slot">${e.slot.toUpperCase()}</span>
                            ${r?W`<span class="pv-name-power">${r}</span>`:q}
                        </div>
                        <input type="text" class="pv-name-input"
                            placeholder=${e.slot.toUpperCase()}
                            .value=${t}
                            @input=${t=>this._onPvNameInput(e.slot,t.target.value)} />
                    </div>`})}
            <div class="section-footer">
                ${"ok"===r?W`<span class="pv-save-ok">✓</span>`:q}
                <button class="pv-save-btn" ?disabled=${"saving"===r}
                        @click=${()=>this._savePvNames()}>
                    ${"saving"===r?"…":this._t("config_pv_strings_save")}
                </button>
            </div>
        `}_renderNotifications(e){const t=this._options||{},i=[{value:"",label:this._t("config_notif_none")}],s=this._hass?.services||{};for(const e of Object.keys(s.notify||{}))i.push({value:e,label:`notify.${e}`});for(const e of Object.keys(s.rest_command||{}))i.push({value:e,label:`rest_command.${e}`});return W`
            <div class="setup-intro">${this._t("config_notifications_intro")}</div>
            ${this._renderOptionToggle("enable_charger_notifications","config_notif_charger",t,"config_help_notif_charger",!0)}
            ${this._renderOptionToggle("enable_mobile_notifications","config_notif_mobile",t,"config_help_notif_mobile",!1)}
            ${this._renderOptionSelect("mobile_notification_service","config_notif_service",i,t,"config_help_notif_service","")}
        `}_renderAdvanced(e){const t=this._options||{};return W`
            ${""}
            <div class="readonly-row" style="border-bottom:1px solid ${e.surfaceBorder};padding-bottom:4px;margin-bottom:4px">
                <span class="ctrl-label" style="font-weight:600">${this._t("config_vpp_section")}</span>
            </div>
            ${this._renderOptionToggle("vpp_enabled","config_vpp_enabled",t,"config_help_vpp_enabled",!1)}
            ${this._renderOptionToggle("vpp_observer_mode","config_vpp_observer",t,"config_help_vpp_observer",!0)}
            ${this._renderPicker("vpp_event_active_entity","config_vpp_event_entity",["binary_sensor","sensor"],null,t,null)}
            ${this._renderPicker("vpp_direction_entity","config_vpp_direction_entity",["sensor","select","input_select"],null,t,null)}
            ${this._renderPicker("vpp_event_end_entity","config_vpp_event_end_entity","sensor","timestamp",t,null)}
            ${this._renderPicker("vpp_pre_event_entity","config_vpp_pre_event_entity",["binary_sensor","sensor"],null,t,null)}
            ${this._renderOptionSlider("vpp_reserve_soc","config_vpp_reserve_soc",{min:5,max:80,step:5,unit:"%",default:20},t,"config_help_vpp_reserve_soc")}
            <div style="margin-top:6px;border-top:1px solid ${e.surfaceBorder};padding-top:4px"></div>
            ${this._renderToggle("switch.sem_observer_mode","observer_mode",e,"config_help_observer_mode")}
            <div class="stepper-pair">
                ${this._renderStepper("number.sem_update_interval","update_interval",e,"config_help_update_interval")}
                ${this._renderStepper("number.sem_minimum_solar_power","min_solar_power",e,"config_help_min_solar_power")}
            </div>
            <div class="stepper-pair">
                ${this._renderStepper("number.sem_regulation_offset","regulation_offset",e,"config_help_regulation_offset")}
                ${this._renderStepper("number.sem_ev_enable_delay_seconds","ev_enable_delay",e,"config_help_ev_enable_delay")}
            </div>
            <div class="stepper-pair">
                ${this._renderStepper("number.sem_ev_disable_delay_seconds","ev_disable_delay",e,"config_help_ev_disable_delay")}
            </div>
            ${this._renderGridSignFix(e)}
        `}_renderGridSignFix(e){const t=this._val("diag_grid_sign")||"—",i=this._val("diag_battery_sign")||"—";return W`
            <div class="grid-sign-block">
                <div class="readonly-row">
                    <span class="ctrl-label">${this._t("grid_sign")}</span>
                    <span class="readonly-value">${t}</span>
                </div>
                <div class="action-row">
                    <button class="action-btn" ?disabled=${this._signBusy}
                            @click=${()=>this._flipGridSign()}>
                        <ha-icon icon="mdi:swap-vertical-bold" style="--mdc-icon-size:16px"></ha-icon>
                        ${this._t("fix_grid_sign")}
                    </button>
                    <button class="action-btn action-btn-ghost"
                            @click=${()=>this._resetSignDetection()}>
                        ${this._t("reset_sign_detection")}
                    </button>
                </div>
                ${this._signMsg?W`<div class="sign-feedback">${this._signMsg}</div>`:q}
                ${this._showHelp?W`<div class="setting-help-text">${this._t("fix_grid_sign_help")}</div>`:q}
                <div class="readonly-row" style="margin-top:8px">
                    <span class="ctrl-label">${this._t("battery_sign")}</span>
                    <span class="readonly-value">${i}</span>
                </div>
                <div class="action-row">
                    <button class="action-btn" ?disabled=${this._battSignBusy}
                            @click=${()=>this._flipBatterySign()}>
                        <ha-icon icon="mdi:swap-vertical-bold" style="--mdc-icon-size:16px"></ha-icon>
                        ${this._t("fix_battery_sign")}
                    </button>
                </div>
                ${this._battSignMsg?W`<div class="sign-feedback">${this._battSignMsg}</div>`:q}
                ${this._showHelp?W`<div class="setting-help-text">${this._t("fix_battery_sign_help")}</div>`:q}
            </div>
        `}_resetSignDetection(){this._hass&&(this._hass.callService("solar_energy_management","reset_sign_detection",{}),this._signMsg=this._t("sign_relearn_started"),this.requestUpdate(),setTimeout(()=>{this._signMsg="",this.requestUpdate()},4e3))}async _flipGridSign(){if(!this._hass||this._signBusy)return;this._signBusy=!0,this._signMsg="",this.requestUpdate();let e=null;try{const t=await this._hass.callService("solar_energy_management","flip_grid_sign",{},void 0,!1,!0);e=t&&t.response?t.response:t}catch(t){e=null}const t=this._buildSignReport(e);let i=!1;try{await navigator.clipboard.writeText(t),i=!0}catch(e){i=!1}this._signBusy=!1,this._signMsg=i?this._t("sign_flipped_copied"):this._t("sign_flipped"),this.requestUpdate(),setTimeout(()=>{this._signMsg="",this.requestUpdate()},6e3)}async _flipBatterySign(){if(!this._hass||this._battSignBusy)return;this._battSignBusy=!0,this._battSignMsg="",this.requestUpdate();let e=null;try{const t=await this._hass.callService("solar_energy_management","flip_battery_sign",{},void 0,!1,!0);e=t&&t.response?t.response:t}catch(t){e=null}const t=this._buildBatterySignReport(e);let i=!1;try{await navigator.clipboard.writeText(t),i=!0}catch(e){i=!1}this._battSignBusy=!1,this._battSignMsg=i?this._t("sign_flipped_copied"):this._t("sign_flipped"),this.requestUpdate(),setTimeout(()=>{this._battSignMsg="",this.requestUpdate()},6e3)}_buildBatterySignReport(e){const t=e&&e.diagnostics||{},i=e&&"boolean"==typeof e.user_flip?String(e.user_flip):"?",s=e=>null==e?"?":String(e),r=e=>Array.isArray(e)&&e.length?e.join(", "):"(none)",a=String.fromCharCode(96),o=e=>a+e+a,n=t.per_bid||{},l=Object.entries(n).map(([e,t])=>"  "+e+": "+s(t.inverted?"negated":"normal")+" (detected="+s(t.detected)+", confidence="+s(t.confidence)+", samples="+s(t.samples)+")");return["### SEM battery-sign report (#588)","","I tapped **Fix battery sign** in the Configuration tab.","battery_sign_user_flip is now "+o(i)+".","","- Battery sensor: "+o(s(t.battery_power_sensor))+" = "+s(t.battery_power_raw_state)+" (raw)","- Battery integration: "+s(t.battery_platform)+" (brand-seeded: "+s(t.brand_seeded)+")","- Per-battery sign state:",...l,"- Charge counters: "+r(t.charge_counters),"- Discharge counters: "+r(t.discharge_counters),"","My hardware (please fill in): inverter / battery brand.","After the flip, does battery charge/discharge show the correct direction?"].join("\n")}_buildSignReport(e){const t=e&&e.diagnostics||{},i=e&&"boolean"==typeof e.user_flip?String(e.user_flip):"?",s=e=>null==e?"?":String(e),r=e=>Array.isArray(e)&&e.length?e.join(", "):"(none)",a=String.fromCharCode(96),o=e=>a+e+a;return["### SEM grid-sign report (#461)","","I tapped **Fix grid sign** in the Configuration tab.","grid_sign_user_flip is now "+o(i)+".","","- Meter sensor: "+o(s(t.grid_power_sensor))+" = "+s(t.grid_power_raw_state)+" (raw)","- Meter integration: "+s(t.grid_platform)+" (brand-seeded: "+s(t.brand_seeded)+")","- Auto-detect: detected="+s(t.auto_detected)+", inverted="+s(t.auto_inverted),"- Manual grid_sign_invert: "+s(t.manual_grid_sign_invert),"- Counter correlation: confidence="+s(t.confidence)+", evidence="+s(t.evidence)+", samples="+s(t.samples),"- Solar correlation: confidence="+s(t.solar_confidence)+", evidence="+s(t.solar_evidence)+", samples="+s(t.solar_samples),"- Seen import="+s(t.seen_import)+", export="+s(t.seen_export),"- Import counters: "+r(t.import_counters),"- Export counters: "+r(t.export_counters),"","My hardware (please fill in): inverter / grid meter / battery brand.","After the flip, do the Home-tab import vs export arrows now point the right way?"].join("\n")}_renderSectionHeader(e,t){const i=this._collapsed[e.id]?"rotate(-90deg)":"rotate(0deg)",s=e.subtitleFn(this),r="overview"===e.id?"all":e.id;return W`
            <div class="section-header" @click=${()=>this._toggleSection(e.id)}>
                <div class="section-dot" style="background:${e.color}"></div>
                <ha-icon icon="${e.icon}" style="--mdc-icon-size:20px;color:${e.color}"></ha-icon>
                <span class="section-title-text">${this._t(e.titleKey)}</span>
                ${this._sectionStaged(e.id).length?W`
                    <span class="header-dirty-badge" title="${this._t("config_pending_hint")}">● ${this._sectionStaged(e.id).length}</span>`:q}
                ${e.docs?W`
                    <a class="section-docs-link" href="${e.docs}" target="_blank" rel="noopener"
                       title="${this._t("config_docs")}" @click=${e=>e.stopPropagation()}>
                        <ha-icon icon="mdi:book-open-variant" style="--mdc-icon-size:15px"></ha-icon>
                    </a>`:q}
                <span class="section-subtitle" style="color:${s?e.color:""}">${s}</span>
                <sem-diagnose-button
                    .hass=${this._hass}
                    section="${r}"
                    label="${this._t("config_diagnose")}"
                    @click=${e=>e.stopPropagation()}>
                </sem-diagnose-button>
                <ha-icon class="chevron" icon="mdi:chevron-down"
                         style="--mdc-icon-size:18px;transform:${i}"></ha-icon>
            </div>
        `}_renderSection(e,t,i){const s=this._collapsed[e.id];this._sec=e.id;const r=t(i);this._sec=null;const a=this._sectionStaged(e.id),o=this._secApplying===e.id,n=this._saveStatus["_sec_"+e.id],l=a.length?W`
            <div class="section-stage-bar">
                <span class="stage-count">● ${a.length} ${this._t("config_unsaved")}</span>
                ${n?W`<span class="stage-err">⚠ ${n}</span>`:q}
                <button class="stage-btn revert" ?disabled=${o}
                        @click=${()=>this._revertSection(e.id)}>↩ ${this._t("config_revert")}</button>
                <button class="stage-btn apply" ?disabled=${o}
                        @click=${()=>this._applySection(e.id)}>${o?W`${this._t("config_saving")}…`:W`✓ ${this._t("config_apply_section")}`}</button>
            </div>`:q;return W`
            <div class="section ${s?"":"expanded"}"
                 style="--section-accent: ${e.color}">
                ${this._renderSectionHeader(e,i)}
                <div class="section-content ${s?"":"expanded"}">
                    <div class="section-body">
                        ${r}
                        ${l}
                    </div>
                </div>
            </div>
        `}render(){if(!this._config)return q;const e=this._theme(),t=!1!==e.isDark,i=e.accent||"#42a5f5",s={overview:e=>this._renderOverview(e),ev_chargers:e=>this._renderEvChargers(e),battery_zones:e=>this._renderBatteryZones(e),tariff:e=>this._renderTariff(e),heat_pump:e=>this._renderHeatPump(e),hot_water:e=>this._renderHotWater(e),battery_scheduler:e=>this._renderBatteryScheduler(e),load_management:e=>this._renderLoadManagement(e),forecast:e=>this._renderForecast(e),pv_strings:e=>this._renderPvStrings(e),notifications:e=>this._renderNotifications(e),advanced:e=>this._renderAdvanced(e)};return W`
            <style>
                :host { display: block; contain: layout style paint; }
                .wrap {
                    padding: 16px 20px;
                    position: relative;
                    background: ${ye(e,"#8DC892")};
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${e.text});
                }
                .card-help-bar {
                    display: flex; justify-content: flex-end;
                    margin: -4px 0 6px;
                }
                .help-toggle {
                    cursor: pointer;
                    color: var(--secondary-text-color, ${e.textSec});
                    opacity: 0.6;
                    flex-shrink: 0;
                    transition: opacity 0.15s, color 0.15s;
                    user-select: none;
                    padding: 4px;
                    border-radius: 50%;
                }
                .help-toggle:hover { opacity: 1; }
                .help-toggle-labeled {
                    display: inline-flex; align-items: center; gap: 5px;
                    padding: 4px 10px; border-radius: 14px;
                    border: 1px solid ${e.surfaceBorder};
                    font-size: 12px; cursor: pointer;
                    color: ${e.textDim||"rgba(150,160,175,0.9)"};
                    transition: color 0.15s, border-color 0.15s;
                }
                .help-toggle-labeled:hover { color: ${i}; border-color: ${i}; }
                .help-toggle-labeled.on { color: ${i}; border-color: ${i}; }
                .help-toggle.on { color: ${i}; opacity: 1; }

                /* ── Sections: same surface shape as the battery card's
                       per-battery sections (.battery-section) so the
                       Config tab reads like the Battery tab. ── */
                .section {
                    margin-bottom: 12px;
                    border-radius: 12px;
                    background: ${e.surface};
                    border: 1px solid ${e.surfaceBorder};
                    overflow: hidden;
                    transition: border-color 0.3s cubic-bezier(0.4,0,0.2,1), box-shadow 0.2s;
                    position: relative;
                }
                .section.expanded {
                    border-color: color-mix(in srgb, var(--section-accent) 40%, ${e.surfaceBorder});
                    box-shadow: inset 3px 0 0 0 var(--section-accent);
                }
                .section:hover { border-color: ${t?"rgba(255,255,255,0.18)":"rgba(0,0,0,0.12)"}; }
                .section-header {
                    display: flex; align-items: center; gap: 8px;
                    padding: 12px 14px; cursor: pointer; user-select: none;
                    transition: background 0.15s;
                }
                .section.expanded .section-header {
                    background: color-mix(in srgb, var(--section-accent) 6%, transparent);
                }
                .section-dot {
                    width: 8px; height: 8px;
                    border-radius: 50%;
                    flex-shrink: 0;
                }
                .section-title-text {
                    font-size: 0.95em; font-weight: 600; white-space: nowrap;
                    color: var(--primary-text-color, ${e.text});
                }
                .section-subtitle {
                    flex: 1; font-size: 0.75em; font-weight: 500;
                    text-transform: uppercase; letter-spacing: 0.05em;
                    color: var(--secondary-text-color, ${e.textSec});
                    text-align: right; white-space: nowrap;
                    overflow: hidden; text-overflow: ellipsis; margin-right: 4px;
                }
                .chevron { transition: transform 0.25s ease; color: var(--secondary-text-color, ${e.textSec}); }
                .section-content {
                    max-height: 0; opacity: 0; overflow: hidden;
                    transition: max-height 0.3s ease, opacity 0.2s ease;
                }
                .section-content.expanded { max-height: 2000px; opacity: 1; }
                .section-body { padding: 0 14px 14px; }
                .section-footer { display: flex; justify-content: flex-end; align-items: center; gap: 10px; margin-top: 10px; }

                /* (#566) PV-string rename rows */
                .pv-name-row {
                    display: flex; align-items: center; gap: 12px;
                    padding: 8px 0;
                }
                .pv-name-meta {
                    display: flex; flex-direction: column; min-width: 64px;
                }
                .pv-name-slot { font-size: 0.9em; font-weight: 700; color: #ff9800; }
                .pv-name-power {
                    font-size: 0.7em; color: var(--secondary-text-color, ${e.textSec});
                }
                .pv-name-input {
                    flex: 1; min-width: 0;
                    background: var(--secondary-background-color, ${e.surface});
                    border: 1px solid var(--divider-color, ${e.surfaceBorder});
                    border-radius: 8px; padding: 8px 10px;
                    color: var(--primary-text-color, ${e.text});
                    font-family: inherit; font-size: 0.9em;
                }
                .pv-name-input:focus { outline: none; border-color: #ff9800; }
                .pv-save-btn {
                    background: #ff9800; color: #1a1a1a; border: none;
                    border-radius: 8px; padding: 7px 16px; cursor: pointer;
                    font-weight: 600; font-size: 0.85em;
                }
                .pv-save-btn:disabled { opacity: 0.6; cursor: default; }
                .pv-save-ok { color: #8DC892; font-weight: 700; }

                /* Overview chips — same shape as the battery card's
                   daily chips (.chip / .chip-label / .chip-value). */
                .chips { display: flex; gap: 8px; margin: 6px 0; flex-wrap: wrap; }
                .chip {
                    flex: 1; min-width: 80px;
                    background: var(--secondary-background-color, ${e.surface});
                    border: 1px solid var(--divider-color, ${e.surfaceBorder});
                    border-radius: 10px; padding: 8px 10px; text-align: center;
                    transition: border-color 0.3s cubic-bezier(0.4,0,0.2,1);
                }
                .chip:hover { border-color: var(--divider-color, ${e.surfaceHover}); }
                .chip-label {
                    font-size: 10px; color: var(--secondary-text-color, ${e.textSec});
                    font-weight: 500; letter-spacing: 0.3px; margin: 3px 0;
                }
                .chip-value { font-size: 13px; font-weight: 600; font-variant-numeric: tabular-nums; }
                .c-ok { color: #8DC892; }
                .c-warn { color: #ff9800; }
                .overview-help { font-size: 12px; color: var(--secondary-text-color, ${e.textSec}); padding: 4px 0; }
                .overview-actions { display: flex; gap: 8px; margin-top: 10px; }

                .empty-state {
                    display: flex; flex-direction: column; align-items: center;
                    gap: 8px; padding: 16px 8px; text-align: center;
                }
                .empty-title { font-size: 14px; font-weight: 600; color: var(--primary-text-color, ${e.text}); }
                .empty-help {
                    font-size: 12px; color: var(--secondary-text-color, ${e.textSec});
                    max-width: 320px; line-height: 1.4;
                }
                .info-box-text { font-size: 13px; color: var(--secondary-text-color, ${e.textSec}); padding: 6px 0; line-height: 1.4; }

                /* Inline edit primitives (same look as Control card) */
                .ctrl-row { display: flex; align-items: center; justify-content: space-between; padding: 8px 0; }
                .ctrl-label { font-size: 14px; font-weight: 500; }
                .sem-select {
                    background: ${e.surface};
                    border: 1px solid ${e.surfaceBorder};
                    border-radius: 8px;
                    color: var(--primary-text-color, ${e.text});
                    padding: 6px 10px; font-size: 14px; font-family: inherit;
                    cursor: pointer; min-width: 120px; outline: none;
                }
                .sem-select option { background: ${t?"#1e232d":"#fff"}; color: ${t?"#e0e0e0":"#333"}; }
                .stepper-row { display: flex; align-items: center; justify-content: space-between; padding: 7px 0; }
                .stepper-label {
                    font-size: 14px; font-weight: 500; flex: 1; min-width: 0;
                    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
                }
                .stepper-controls { display: flex; align-items: center; gap: 2px; flex-shrink: 0; }
                .stepper-minus, .stepper-plus {
                    width: 30px; height: 30px; border-radius: 8px;
                    border: 1px solid ${e.surfaceBorder};
                    background: ${e.surface}; color: var(--primary-text-color, ${e.text});
                    font-size: 16px; font-weight: 600; cursor: pointer;
                    display: flex; align-items: center; justify-content: center;
                    transition: background 0.15s, border-color 0.15s; user-select: none;
                    padding: 0; line-height: 1;
                }
                .stepper-minus:hover, .stepper-plus:hover { background: ${e.surfaceHover}; border-color: ${i}; }
                .stepper-value {
                    font-size: 14px; font-weight: 600; min-width: 60px; text-align: center;
                    font-variant-numeric: tabular-nums;
                }
                .stepper-pair { display: grid; grid-template-columns: 1fr 1fr; gap: 0 16px; }
                @media (max-width: 480px) { .stepper-pair { grid-template-columns: 1fr; } }
                .readonly-row { display: flex; align-items: center; justify-content: space-between; padding: 7px 0; }
                .readonly-row .ctrl-label { font-size: 12px; color: var(--secondary-text-color, ${e.textSec}); font-weight: 500; }
                .readonly-value {
                    font-size: 13px; font-weight: 600; font-variant-numeric: tabular-nums;
                    color: var(--primary-text-color, ${e.text});
                }
                /* #461 grid-sign fix block */
                .grid-sign-block { margin-top: 6px; padding-top: 8px; border-top: 1px solid ${e.surfaceBorder}; }
                .grid-sign-block .action-row { display: flex; justify-content: flex-end; gap: 8px; padding: 6px 0 2px; }
                .grid-sign-block .action-btn {
                    display: inline-flex; align-items: center; gap: 6px;
                    padding: 7px 14px; border-radius: 9px; cursor: pointer;
                    font-size: 13px; font-weight: 600;
                    color: var(--primary-text-color, ${e.text});
                    background: var(--secondary-background-color, rgba(255,255,255,0.07));
                    border: 1px solid var(--divider-color, ${e.surfaceBorder});
                    transition: background 0.15s;
                }
                .grid-sign-block .action-btn:hover { background: rgba(255,255,255,0.13); }
                .grid-sign-block .action-btn[disabled] { opacity: 0.5; cursor: default; }
                .grid-sign-block .action-btn-ghost {
                    background: transparent; font-weight: 500;
                    color: var(--secondary-text-color, ${e.textSec});
                }
                .grid-sign-block .sign-feedback {
                    text-align: right; font-size: 12px; padding: 4px 0 2px;
                    color: var(--secondary-text-color, ${e.textSec});
                }
                .tariff-rate-row { gap: 8px; border-bottom: 1px solid ${e.surfaceBorder}; margin-bottom: 8px; padding-bottom: 10px; }
                .tariff-rate-value { font-size: 15px; font-weight: 700; color: ${e.text}; }
                .toggle-row { display: flex; align-items: center; justify-content: space-between; padding: 8px 0; }
                .toggle-label { font-size: 14px; font-weight: 500; }
                .toggle-track {
                    position: relative; width: 42px; height: 24px;
                    border-radius: 12px;
                    background: ${t?"rgba(255,255,255,0.15)":"rgba(0,0,0,0.18)"};
                    cursor: pointer; transition: background 0.2s; flex-shrink: 0;
                }
                .toggle-track.on { background: ${i}; }
                .toggle-thumb {
                    position: absolute; top: 2px; left: 2px;
                    width: 20px; height: 20px; border-radius: 50%;
                    background: white; box-shadow: 0 1px 3px rgba(0,0,0,0.3);
                    transition: left 0.2s;
                }
                .toggle-track.on .toggle-thumb { left: 20px; }

                .stepper-cell { display: flex; flex-direction: column; }

                /* ── #528: colorful zone controls (battery design language) ── */
                .zone-knob { padding: 8px 2px 10px; }
                .zone-knob-top {
                    display: flex; align-items: center; justify-content: space-between;
                    margin-bottom: 7px;
                }
                .zone-knob-label { font-size: 14px; font-weight: 600; }
                .zone-chip {
                    background: color-mix(in srgb, var(--section-accent) 18%, transparent);
                    color: var(--section-accent);
                    font-weight: 700; font-size: 0.92em;
                    padding: 2px 11px; border-radius: 11px;
                    border: 1px solid color-mix(in srgb, var(--section-accent) 40%, transparent);
                    min-width: 56px; text-align: center;
                }
                .zone-knob-slider { display: flex; align-items: center; gap: 10px; }
                .zone-mini {
                    width: 28px; height: 28px; flex-shrink: 0;
                    border-radius: 8px; cursor: pointer;
                    border: 1px solid color-mix(in srgb, var(--section-accent) 35%, ${e.surfaceBorder});
                    background: color-mix(in srgb, var(--section-accent) 8%, transparent);
                    color: var(--section-accent);
                    font-size: 18px; line-height: 1; font-weight: 600;
                    display: flex; align-items: center; justify-content: center;
                    transition: background 0.12s;
                }
                .zone-mini:hover { background: color-mix(in srgb, var(--section-accent) 20%, transparent); }
                .zone-range {
                    -webkit-appearance: none; appearance: none;
                    flex: 1; min-width: 0; height: 6px; border-radius: 3px;
                    cursor: pointer; outline: none;
                    background: linear-gradient(to right,
                        var(--section-accent) 0%, var(--section-accent) var(--fill, 0%),
                        ${t?"rgba(255,255,255,0.14)":"rgba(0,0,0,0.12)"} var(--fill, 0%),
                        ${t?"rgba(255,255,255,0.14)":"rgba(0,0,0,0.12)"} 100%);
                }
                .zone-range::-webkit-slider-thumb {
                    -webkit-appearance: none; width: 16px; height: 16px; border-radius: 50%;
                    background: var(--section-accent); border: 2px solid #fff;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.45); cursor: pointer;
                }
                .zone-range::-moz-range-thumb {
                    width: 16px; height: 16px; border-radius: 50%;
                    background: var(--section-accent); border: 2px solid #fff;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.45); cursor: pointer;
                }

                /* SOC-zone strip */
                .soc-strip { padding: 4px 2px 12px; }
                .soc-bar {
                    position: relative; display: flex;
                    height: 14px; border-radius: 7px; overflow: hidden;
                    margin-bottom: 22px;
                }
                .soc-zone { height: 100%; }
                .soc-now {
                    position: absolute; top: -3px; width: 3px; height: 20px;
                    background: #fff; border-radius: 2px;
                    box-shadow: 0 0 4px rgba(0,0,0,0.6); transform: translateX(-50%);
                }
                .soc-tick {
                    position: absolute; bottom: -20px; transform: translateX(-50%);
                    font-size: 10px; color: var(--secondary-text-color, ${e.textSec});
                }
                .soc-tick::before {
                    content: ''; position: absolute; top: -7px; left: 50%;
                    width: 1px; height: 6px; background: var(--secondary-text-color, ${e.textSec});
                    opacity: 0.5; transform: translateX(-50%);
                }
                .soc-legend {
                    display: flex; flex-wrap: wrap; gap: 4px 14px;
                    font-size: 11px; color: var(--secondary-text-color, ${e.textSec});
                }
                .soc-legend span { display: inline-flex; align-items: center; gap: 5px; }
                .soc-legend i { width: 9px; height: 9px; border-radius: 2px; display: inline-block; }

                /* #528 staged-changes Apply bar (sticky at top of the card) */
                .apply-bar {
                    position: sticky; top: 6px; z-index: 5;
                    display: flex; align-items: center; gap: 10px;
                    margin: 0 0 12px; padding: 9px 12px;
                    border-radius: 10px;
                    background: color-mix(in srgb, ${i} 16%, ${e.surface});
                    border: 1px solid color-mix(in srgb, ${i} 45%, ${e.surfaceBorder});
                    box-shadow: 0 2px 10px rgba(0,0,0,0.25);
                }
                .apply-msg { flex: 1; font-size: 12.5px; font-weight: 600;
                    display: inline-flex; align-items: center; gap: 8px; }
                .apply-btn, .apply-discard {
                    border: none; border-radius: 8px; cursor: pointer;
                    font-size: 12.5px; font-weight: 700; padding: 6px 14px;
                }
                .apply-btn { background: ${i}; color: #fff; }
                .apply-discard {
                    background: transparent; color: var(--secondary-text-color, ${e.textSec});
                    border: 1px solid ${e.surfaceBorder};
                }
                .apply-spin {
                    width: 13px; height: 13px; border-radius: 50%;
                    border: 2px solid color-mix(in srgb, ${i} 30%, transparent);
                    border-top-color: ${i}; display: inline-block;
                    animation: applyspin 0.7s linear infinite;
                }
                @keyframes applyspin { to { transform: rotate(360deg); } }
                .apply-bar.apply-err {
                    background: color-mix(in srgb, #e57373 18%, ${e.surface});
                    border-color: color-mix(in srgb, #e57373 55%, ${e.surfaceBorder});
                }
                .apply-bar.apply-err .apply-msg { color: #e57373; }
                .pending-dot { color: ${i}; font-size: 9px; margin-left: 6px; vertical-align: middle; }

                /* #528 Phase 4 — add/remove charger */
                .add-charger-btn {
                    display: inline-flex; align-items: center; gap: 6px;
                    margin-top: 8px; padding: 8px 16px; border-radius: 9px; cursor: pointer;
                    background: color-mix(in srgb, #5BC8D8 16%, transparent);
                    border: 1px dashed color-mix(in srgb, #5BC8D8 55%, ${e.surfaceBorder});
                    color: #5BC8D8; font-size: 13px; font-weight: 700;
                }
                .add-charger-btn:hover { background: color-mix(in srgb, #5BC8D8 28%, transparent); }
                .add-charger-btn[disabled] { opacity: 0.5; cursor: default; }
                .charger-remove-x {
                    border: none; background: transparent; cursor: pointer;
                    color: var(--secondary-text-color, ${e.textSec}); font-size: 14px;
                    padding: 2px 6px; border-radius: 6px; line-height: 1;
                }
                .charger-remove-x:hover { color: #e57373; background: color-mix(in srgb, #e57373 15%, transparent); }
                .charger-remove-confirm {
                    display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
                    margin: 4px 0 8px; padding: 8px 10px; border-radius: 8px;
                    background: color-mix(in srgb, #e57373 14%, ${e.surface});
                    border: 1px solid color-mix(in srgb, #e57373 45%, ${e.surfaceBorder});
                    font-size: 12.5px;
                }
                .charger-remove-confirm span { flex: 1; }
                .charger-remove-go {
                    border: none; border-radius: 7px; cursor: pointer; font-weight: 700;
                    padding: 5px 12px; background: #e57373; color: #fff; font-size: 12px;
                }
                .charger-remove-cancel {
                    border: 1px solid ${e.surfaceBorder}; border-radius: 7px; cursor: pointer;
                    padding: 5px 12px; background: transparent;
                    color: var(--secondary-text-color, ${e.textSec}); font-size: 12px;
                }

                /* #528 first-run completeness guide */
                .setup-progress { margin: 2px 2px 12px; }
                .setup-progress-top {
                    display: flex; justify-content: space-between; align-items: baseline;
                    margin-bottom: 6px;
                }
                .setup-progress-label { font-size: 13px; font-weight: 700; }
                .setup-progress-pct { font-size: 12px; color: var(--secondary-text-color, ${e.textSec}); }
                .setup-progress-bar {
                    height: 7px; border-radius: 4px; overflow: hidden;
                    background: ${t?"rgba(255,255,255,0.12)":"rgba(0,0,0,0.1)"};
                }
                .setup-progress-fill {
                    height: 100%; border-radius: 4px;
                    background: #ffb74d; transition: width 0.4s cubic-bezier(0.4,0,0.2,1);
                }
                .setup-progress-fill.done { background: #81c784; }
                .chip-todo { cursor: pointer; border-style: dashed !important; }
                .chip-todo:hover { border-color: ${i} !important; }
                .chip-todo .c-warn { color: ${i} !important; font-weight: 700; white-space: nowrap; }

                .setting-help-text {
                    font-size: 11px; line-height: 1.35;
                    color: var(--secondary-text-color, ${e.textSec});
                    opacity: 0.75; padding: 2px 4px 6px 0; margin-top: -4px;
                    font-style: italic;
                }

                /* Entity picker + slider cells for option-only fields */
                .picker-cell { display: flex; flex-direction: column; padding: 6px 0; }
                .picker-row { display: flex; align-items: center; gap: 10px; }
                .picker-label {
                    font-size: 14px; font-weight: 500;
                    min-width: 150px; flex-shrink: 0;
                }
                .picker-row ha-entity-picker { flex: 1; min-width: 0; }
                .save-status {
                    font-size: 11px; padding: 2px 0 0 154px;
                    color: var(--secondary-text-color, ${e.textSec});
                }
                .save-status.ok { color: #8DC892; }
                .save-status.err { color: var(--error-color, #d33); }

                .setup-intro {
                    font-size: 12px; line-height: 1.45;
                    color: var(--secondary-text-color, ${e.textSec});
                    padding: 6px 0 12px; border-bottom: 1px solid ${e.surfaceBorder};
                    margin-bottom: 8px;
                }
                .hp-status, .hp-form { display: flex; flex-direction: column; }
                .hp-status { margin-bottom: 6px; padding-bottom: 6px; border-bottom: 1px solid ${e.surfaceBorder}; }

                /* number input for box-mode large-range fields */
                .num-input-wrap { display: flex; align-items: center; gap: 6px; }
                .sem-num-input {
                    background: ${e.surface};
                    border: 1px solid ${e.surfaceBorder};
                    border-radius: 8px;
                    color: var(--primary-text-color, ${e.text});
                    padding: 5px 8px; font-size: 14px; font-family: inherit;
                    width: 90px; text-align: right;
                    font-variant-numeric: tabular-nums;
                    outline: none;
                }
                .sem-num-input:focus { border-color: ${i}; }
                .num-unit {
                    font-size: 12px; color: var(--secondary-text-color, ${e.textSec});
                }

                @media (max-width: 500px) {
                    .picker-row { flex-wrap: wrap; }
                    .picker-label { flex: 1 1 100%; min-width: 0; }
                    .picker-row ha-entity-picker { flex: 1 1 100%; }
                    .save-status { padding-left: 0; }
                }

                .charger-block {
                    border-left: 3px solid ${i};
                    padding: 6px 0 6px 10px; margin-bottom: 10px;
                }
                .charger-block-title {
                    display: flex; align-items: center; gap: 6px;
                    font-size: 14px; font-weight: 600;
                    margin-bottom: 6px;
                }

                .ha-settings-btn {
                    display: inline-flex; align-items: center; gap: 4px;
                    padding: 6px 12px; border-radius: 8px;
                    background: ${e.surface}; border: 1px solid ${e.surfaceBorder};
                    color: var(--primary-text-color, ${e.text});
                    font-size: 13px; cursor: pointer;
                    transition: background 0.15s, border-color 0.15s;
                }
                .ha-settings-btn:hover { background: ${e.surfaceHover}; border-color: ${i}; }

                /* ── #605 staged-changes UI ── */
                .zone-knob.dirty, .stepper-cell.dirty {
                    border-left: 3px solid var(--section-accent, ${i});
                    padding-left: 8px; margin-left: -11px;
                    border-radius: 4px;
                }
                .dirty-dot {
                    color: var(--section-accent, ${i});
                    font-size: 10px; margin: 0 4px; vertical-align: middle;
                }
                .section-stage-bar {
                    display: flex; align-items: center; gap: 10px;
                    margin-top: 12px; padding: 8px 12px;
                    background: ${e.surface}; border: 1px solid var(--section-accent, ${i});
                    border-radius: 10px;
                    position: sticky; bottom: 8px; z-index: 3;
                    backdrop-filter: blur(8px);
                }
                .stage-count { font-size: 12.5px; color: var(--section-accent, ${i}); font-weight: 600; flex: 1; }
                .stage-err { font-size: 12px; color: #ef5350; }
                .stage-btn {
                    padding: 6px 14px; border-radius: 8px; font-size: 13px;
                    cursor: pointer; border: 1px solid ${e.surfaceBorder};
                    background: ${e.surface}; color: var(--primary-text-color, ${e.text});
                    transition: background 0.15s, border-color 0.15s;
                }
                .stage-btn.apply {
                    background: var(--section-accent, ${i}); color: #fff;
                    border-color: transparent; font-weight: 600;
                }
                .stage-btn:disabled { opacity: 0.55; cursor: default; }
                .stage-btn:not(:disabled):hover { filter: brightness(1.12); }
                .header-dirty-badge {
                    font-size: 11px; font-weight: 700;
                    color: var(--section-accent, ${i});
                    margin-left: 6px; white-space: nowrap;
                }

                /* ── #606 per-row help + defaults + docs ── */
                .row-help-btn {
                    color: ${e.textDim||"rgba(150,160,175,0.8)"};
                    cursor: pointer; margin-left: 5px; vertical-align: middle;
                    opacity: 0.7; transition: opacity 0.15s, color 0.15s;
                }
                .row-help-btn:hover { opacity: 1; }
                .row-help-btn.on { color: var(--section-accent, ${i}); opacity: 1; }
                .help-default {
                    display: inline-block; margin-left: 8px;
                    font-size: 11px; font-weight: 600;
                    color: var(--section-accent, ${i});
                    opacity: 0.9; white-space: nowrap;
                }
                .section-docs-link {
                    display: inline-flex; align-items: center;
                    color: ${e.textDim||"rgba(150,160,175,0.8)"};
                    margin-left: 6px; opacity: 0.7; transition: opacity 0.15s;
                }
                .section-docs-link:hover { opacity: 1; color: var(--section-accent, ${i}); }
                .help-reset-btn {
                    display: inline-block; margin-left: 8px;
                    padding: 1px 8px; border-radius: 9px;
                    font-size: 11px; cursor: pointer;
                    border: 1px solid ${e.surfaceBorder};
                    background: transparent;
                    color: var(--section-accent, ${i});
                }
                .help-reset-btn:hover { border-color: var(--section-accent, ${i}); }
            </style>
            <ha-card>
                <div class="wrap">
                    ${""}
                    <div class="card-help-bar">
                        <span class="help-toggle-labeled ${this._showHelp?"on":""}"
                              @click=${()=>this._toggleHelp()}>
                            <ha-icon
                                icon="${this._showHelp?"mdi:help-circle":"mdi:help-circle-outline"}"
                                style="--mdc-icon-size:16px"
                            ></ha-icon>
                            <span>${this._t("config_help_label")}</span>
                        </span>
                    </div>
                    ${this._renderApplyBar()}
                    ${Xt.filter(e=>"pv_strings"!==e.id||this._pvStrings().length>=2).map(t=>this._renderSection(t,s[t.id],e))}
                </div>
            </ha-card>
        `}getCardSize(){return 12}static getStubConfig(){return{entity_prefix:"sensor.sem_"}}},{type:"custom:sem-config-card",name:"SEM Configuration Card",description:"In-dashboard SEM configuration surface (replaces the Settings → SEM → Configure flow for most users)",preview:!1});const Qt="sem-config-tab-introduced-v1";$e("sem-onboarding-banner",class extends ke{static get watchedEntities(){return[]}static get properties(){return{...super.properties,_dismissed:{state:!0}}}constructor(){super(),this._dismissed=this._isDismissed()}setConfig(e){super.setConfig(e),this._configPath=e.config_tab_path||"/config"}_isDismissed(){try{return"1"===localStorage.getItem(Qt)}catch(e){return!1}}_dismiss(){try{localStorage.setItem(Qt,"1")}catch(e){}this._dismissed=!0}_openConfig(){const e=window.location.pathname.split("/").filter(Boolean);if(e.length>=2){const t="/"+e.slice(0,-1).join("/");window.history.pushState(null,"",`${t}/config`)}else window.history.pushState(null,"",this._configPath);window.dispatchEvent(new Event("location-changed",{composed:!0})),this._dismiss()}render(){if(this._dismissed)return q;if(!this._config)return q;const e=this._theme(),t="#8DC892";return W`
            <style>
                :host { display: block; }
                .banner {
                    display: flex; align-items: center; gap: 12px;
                    padding: 14px 16px; border-radius: 14px; margin-bottom: 12px;
                    background:
                        linear-gradient(135deg, ${t}22 0%, ${t}0B 100%),
                        ${e.surface};
                    border: 1px solid ${t}55;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
                    color: var(--primary-text-color, ${e.text});
                    font-family: 'Segoe UI','Roboto',sans-serif;
                }
                .icon {
                    --mdc-icon-size: 28px;
                    color: ${t};
                    flex-shrink: 0;
                }
                .text { flex: 1; min-width: 0; }
                .title {
                    font-size: 14px; font-weight: 700; letter-spacing: 0.2px;
                    margin-bottom: 2px;
                }
                .body {
                    font-size: 12px; line-height: 1.4;
                    color: var(--secondary-text-color, ${e.textSec});
                }
                .actions { display: flex; gap: 6px; flex-shrink: 0; }
                button {
                    padding: 7px 14px; border-radius: 9px;
                    font-size: 12px; font-weight: 600; font-family: inherit;
                    cursor: pointer; border: 1px solid transparent;
                    transition: background 0.15s, border-color 0.15s, transform 0.05s;
                }
                button:active { transform: scale(0.97); }
                .open {
                    background: ${t}; color: #1a1d24;
                }
                .open:hover { background: color-mix(in srgb, ${t} 88%, white); }
                .dismiss {
                    background: transparent; color: var(--secondary-text-color, ${e.textSec});
                    border-color: ${e.surfaceBorder};
                }
                .dismiss:hover { background: ${e.surfaceHover}; }
                @media (max-width: 500px) {
                    .banner { flex-wrap: wrap; }
                    .text { flex: 1 1 100%; order: 1; }
                    .icon { order: 0; }
                    .actions { flex: 1 1 100%; order: 2; justify-content: flex-end; }
                }
            </style>
            <div class="banner">
                <ha-icon class="icon" icon="mdi:cog-sync-outline"></ha-icon>
                <div class="text">
                    <div class="title">${this._t("onboarding_banner_title")}</div>
                    <div class="body">${this._t("onboarding_banner_body")}</div>
                </div>
                <div class="actions">
                    <button class="open" @click=${()=>this._openConfig()}>
                        ${this._t("onboarding_banner_open")}
                    </button>
                    <button class="dismiss" @click=${()=>this._dismiss()}>
                        ${this._t("onboarding_banner_dismiss")}
                    </button>
                </div>
            </div>
        `}getCardSize(){return 1}static getStubConfig(){return{}}},{type:"custom:sem-onboarding-banner",name:"SEM Onboarding Banner",description:"One-time welcome banner pointing existing users to the new Configuration tab",preview:!1});class ei extends ke{static get properties(){return{...super.properties,section:{type:String},label:{type:String},_open:{state:!0},_busy:{state:!0},_payload:{state:!0},_error:{state:!0},_copied:{state:!0}}}constructor(){super(),this.section="all",this.label="",this._open=!1,this._busy=!1,this._payload=null,this._error=null,this._copied=!1,this._copiedTimer=null}disconnectedCallback(){super.disconnectedCallback(),this._copiedTimer&&(clearTimeout(this._copiedTimer),this._copiedTimer=null)}static get watchedEntities(){return[]}async _click(){if(this._hass){this._open=!0,this._busy=!0,this._error=null,this._payload=null;try{const e=await this._hass.callService("solar_energy_management","diagnose",{section:this.section||"all"},void 0,void 0,!0);this._payload=e?.response||e}catch(e){this._error=e?.message||String(e),console.error("[sem-diagnose-button] failed",e)}finally{this._busy=!1}}}_close(){this._open=!1,this._copied=!1,this._payload=null,this._error=null}async _copy(){if(!this._payload)return;const e=JSON.stringify(this._payload,null,2),t=()=>{this._copied=!0,this._error=null,this._copiedTimer&&clearTimeout(this._copiedTimer),this._copiedTimer=setTimeout(()=>{this._copiedTimer=null,this._copied=!1},1500)};if(navigator?.clipboard?.writeText&&!1!==window.isSecureContext)try{return await navigator.clipboard.writeText(e),void t()}catch(e){console.warn("[sem-diagnose-button] modern clipboard refused, falling back to execCommand",e)}try{const i=document.createElement("textarea");i.value=e,i.setAttribute("readonly",""),i.style.position="fixed",i.style.top="0",i.style.left="0",i.style.width="1px",i.style.height="1px",i.style.opacity="0",document.body.appendChild(i),i.focus(),i.select();const s=document.execCommand("copy");if(document.body.removeChild(i),s)return void t();console.error('[sem-diagnose-button] execCommand("copy") returned false')}catch(e){console.error("[sem-diagnose-button] legacy clipboard fallback threw",e)}this._error=this._t("config_diagnose_clipboard_failed")}render(){const e=this._theme(),t=e.accent||"#5BC8D8",i=this.label||this._t("config_diagnose");return W`
            <style>
                :host { display: inline-flex; }
                .btn {
                    display: inline-flex; align-items: center; gap: 4px;
                    padding: 5px 10px; border-radius: 8px; cursor: pointer;
                    background: ${e.surface}; color: var(--primary-text-color, ${e.text});
                    border: 1px solid ${e.surfaceBorder};
                    font-size: 12px; font-family: inherit;
                    transition: background 0.15s, border-color 0.15s;
                }
                .btn:hover { background: ${e.surfaceHover}; border-color: ${t}; }
                .modal-backdrop {
                    position: fixed; inset: 0;
                    background: rgba(0,0,0,0.72);
                    backdrop-filter: blur(6px);
                    -webkit-backdrop-filter: blur(6px);
                    display: flex; align-items: center; justify-content: center;
                    z-index: 9999; padding: 20px;
                }
                .modal {
                    background: var(--ha-card-background, var(--card-background-color, #1a1d24));
                    border: 1px solid ${e.surfaceBorder};
                    border-radius: 14px; padding: 18px;
                    max-width: 800px; width: 100%;
                    max-height: 80vh; overflow: hidden;
                    display: flex; flex-direction: column;
                    box-shadow: 0 12px 40px rgba(0,0,0,0.65);
                    color: var(--primary-text-color, ${e.text});
                    font-family: 'Segoe UI','Roboto',sans-serif;
                }
                .modal-header {
                    display: flex; align-items: center; gap: 10px;
                    padding-bottom: 12px;
                    border-bottom: 1px solid ${e.surfaceBorder};
                }
                .modal-title { font-size: 16px; font-weight: 700; flex: 1; }
                .icon-btn {
                    background: transparent; border: none;
                    color: var(--secondary-text-color, ${e.textSec});
                    cursor: pointer; padding: 4px; border-radius: 50%;
                    transition: background 0.15s;
                }
                .icon-btn:hover { background: ${e.surfaceHover}; }
                .modal-body {
                    flex: 1; overflow: auto; padding: 12px 0;
                    font-family: ui-monospace, 'SF Mono', 'Roboto Mono', monospace;
                    font-size: 11px; line-height: 1.5;
                    white-space: pre-wrap; word-break: break-word;
                    color: var(--primary-text-color, ${e.text});
                }
                .modal-footer {
                    display: flex; gap: 8px; padding-top: 12px;
                    border-top: 1px solid ${e.surfaceBorder};
                    justify-content: flex-end;
                }
                .footer-btn {
                    padding: 7px 14px; border-radius: 9px;
                    font-size: 12px; font-weight: 600; font-family: inherit;
                    cursor: pointer; border: 1px solid transparent;
                }
                .footer-btn.primary {
                    background: ${t}; color: #1a1d24;
                    border-color: ${t};
                }
                .footer-btn.primary:hover {
                    background: color-mix(in srgb, ${t} 88%, white);
                }
                .footer-btn.secondary {
                    background: transparent;
                    color: var(--secondary-text-color, ${e.textSec});
                    border-color: ${e.surfaceBorder};
                }
                .footer-btn.secondary:hover { background: ${e.surfaceHover}; }
                .footer-btn.copied {
                    background: #8DC892; color: #1a1d24;
                    border-color: #8DC892;
                }
                .busy {
                    text-align: center; padding: 30px;
                    color: var(--secondary-text-color, ${e.textSec});
                }
                .error {
                    color: var(--error-color, #d33);
                    padding: 12px;
                    background: rgba(220, 50, 50, 0.1);
                    border-radius: 8px;
                    font-family: ui-monospace, monospace;
                    font-size: 11px;
                }
            </style>
            <button class="btn" @click=${this._click}>
                <ha-icon icon="mdi:stethoscope" style="--mdc-icon-size:14px"></ha-icon>
                ${i}
            </button>
            ${this._open?W`
                <div class="modal-backdrop" @click=${e=>e.target.classList.contains("modal-backdrop")&&this._close()}>
                    <div class="modal">
                        <div class="modal-header">
                            <ha-icon icon="mdi:stethoscope" style="--mdc-icon-size:18px;color:${t}"></ha-icon>
                            <span class="modal-title">${this._t("config_diagnose")} — ${this.section}</span>
                            <button class="icon-btn" @click=${this._close} title="${this._t("cancel")||"Close"}">
                                <ha-icon icon="mdi:close" style="--mdc-icon-size:18px"></ha-icon>
                            </button>
                        </div>
                        <div class="modal-body">
                            ${this._busy?W`<div class="busy">${this._t("config_diagnose_busy")||"Collecting diagnostics…"}</div>`:q}
                            ${this._error?W`<div class="error">${this._error}</div>`:q}
                            ${this._busy||this._error||!this._payload?q:W`${JSON.stringify(this._payload,null,2)}`}
                        </div>
                        <div class="modal-footer">
                            <button class="footer-btn secondary" @click=${this._close}>
                                ${this._t("cancel")||"Close"}
                            </button>
                            ${this._payload?W`
                                <button class="footer-btn ${this._copied?"copied":"primary"}" @click=${this._copy}>
                                    ${this._copied?this._t("copied"):this._t("config_diagnose_copy")||"Copy to clipboard"}
                                </button>
                            `:q}
                        </div>
                    </div>
                </div>
            `:q}
        `}}customElements.get("sem-diagnose-button")||customElements.define("sem-diagnose-button",ei),console.info("%c SEM Cards %c Lit Bundle ","color: #4db6ac; font-weight: bold; background: #1e232d; padding: 2px 6px; border-radius: 4px 0 0 4px;","color: #ff9800; background: #1e232d; padding: 2px 6px; border-radius: 0 4px 4px 0;");
