const t=globalThis,e=t.ShadowRoot&&(void 0===t.ShadyCSS||t.ShadyCSS.nativeShadow)&&"adoptedStyleSheets"in Document.prototype&&"replace"in CSSStyleSheet.prototype,i=Symbol(),s=new WeakMap;let r=class{constructor(t,e,s){if(this._$cssResult$=!0,s!==i)throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");this.cssText=t,this.t=e}get styleSheet(){let t=this.o;const i=this.t;if(e&&void 0===t){const e=void 0!==i&&1===i.length;e&&(t=s.get(i)),void 0===t&&((this.o=t=new CSSStyleSheet).replaceSync(this.cssText),e&&s.set(i,t))}return t}toString(){return this.cssText}};const a=(t,...e)=>{const s=1===t.length?t[0]:e.reduce((e,i,s)=>e+(t=>{if(!0===t._$cssResult$)return t.cssText;if("number"==typeof t)return t;throw Error("Value passed to 'css' function must be a 'css' function result: "+t+". Use 'unsafeCSS' to pass non-literal values, but take care to ensure page security.")})(i)+t[s+1],t[0]);return new r(s,t,i)},o=e?t=>t:t=>t instanceof CSSStyleSheet?(t=>{let e="";for(const i of t.cssRules)e+=i.cssText;return(t=>new r("string"==typeof t?t:t+"",void 0,i))(e)})(t):t,{is:n,defineProperty:l,getOwnPropertyDescriptor:c,getOwnPropertyNames:d,getOwnPropertySymbols:p,getPrototypeOf:h}=Object,_=globalThis,g=_.trustedTypes,u=g?g.emptyScript:"",f=_.reactiveElementPolyfillSupport,m=(t,e)=>t,v={toAttribute(t,e){switch(e){case Boolean:t=t?u:null;break;case Object:case Array:t=null==t?t:JSON.stringify(t)}return t},fromAttribute(t,e){let i=t;switch(e){case Boolean:i=null!==t;break;case Number:i=null===t?null:Number(t);break;case Object:case Array:try{i=JSON.parse(t)}catch(t){i=null}}return i}},y=(t,e)=>!n(t,e),x={attribute:!0,type:String,converter:v,reflect:!1,useDefault:!1,hasChanged:y};Symbol.metadata??=Symbol("metadata"),_.litPropertyMetadata??=new WeakMap;let b=class extends HTMLElement{static addInitializer(t){this._$Ei(),(this.l??=[]).push(t)}static get observedAttributes(){return this.finalize(),this._$Eh&&[...this._$Eh.keys()]}static createProperty(t,e=x){if(e.state&&(e.attribute=!1),this._$Ei(),this.prototype.hasOwnProperty(t)&&((e=Object.create(e)).wrapped=!0),this.elementProperties.set(t,e),!e.noAccessor){const i=Symbol(),s=this.getPropertyDescriptor(t,i,e);void 0!==s&&l(this.prototype,t,s)}}static getPropertyDescriptor(t,e,i){const{get:s,set:r}=c(this.prototype,t)??{get(){return this[e]},set(t){this[e]=t}};return{get:s,set(e){const a=s?.call(this);r?.call(this,e),this.requestUpdate(t,a,i)},configurable:!0,enumerable:!0}}static getPropertyOptions(t){return this.elementProperties.get(t)??x}static _$Ei(){if(this.hasOwnProperty(m("elementProperties")))return;const t=h(this);t.finalize(),void 0!==t.l&&(this.l=[...t.l]),this.elementProperties=new Map(t.elementProperties)}static finalize(){if(this.hasOwnProperty(m("finalized")))return;if(this.finalized=!0,this._$Ei(),this.hasOwnProperty(m("properties"))){const t=this.properties,e=[...d(t),...p(t)];for(const i of e)this.createProperty(i,t[i])}const t=this[Symbol.metadata];if(null!==t){const e=litPropertyMetadata.get(t);if(void 0!==e)for(const[t,i]of e)this.elementProperties.set(t,i)}this._$Eh=new Map;for(const[t,e]of this.elementProperties){const i=this._$Eu(t,e);void 0!==i&&this._$Eh.set(i,t)}this.elementStyles=this.finalizeStyles(this.styles)}static finalizeStyles(t){const e=[];if(Array.isArray(t)){const i=new Set(t.flat(1/0).reverse());for(const t of i)e.unshift(o(t))}else void 0!==t&&e.push(o(t));return e}static _$Eu(t,e){const i=e.attribute;return!1===i?void 0:"string"==typeof i?i:"string"==typeof t?t.toLowerCase():void 0}constructor(){super(),this._$Ep=void 0,this.isUpdatePending=!1,this.hasUpdated=!1,this._$Em=null,this._$Ev()}_$Ev(){this._$ES=new Promise(t=>this.enableUpdating=t),this._$AL=new Map,this._$E_(),this.requestUpdate(),this.constructor.l?.forEach(t=>t(this))}addController(t){(this._$EO??=new Set).add(t),void 0!==this.renderRoot&&this.isConnected&&t.hostConnected?.()}removeController(t){this._$EO?.delete(t)}_$E_(){const t=new Map,e=this.constructor.elementProperties;for(const i of e.keys())this.hasOwnProperty(i)&&(t.set(i,this[i]),delete this[i]);t.size>0&&(this._$Ep=t)}createRenderRoot(){const i=this.shadowRoot??this.attachShadow(this.constructor.shadowRootOptions);return((i,s)=>{if(e)i.adoptedStyleSheets=s.map(t=>t instanceof CSSStyleSheet?t:t.styleSheet);else for(const e of s){const s=document.createElement("style"),r=t.litNonce;void 0!==r&&s.setAttribute("nonce",r),s.textContent=e.cssText,i.appendChild(s)}})(i,this.constructor.elementStyles),i}connectedCallback(){this.renderRoot??=this.createRenderRoot(),this.enableUpdating(!0),this._$EO?.forEach(t=>t.hostConnected?.())}enableUpdating(t){}disconnectedCallback(){this._$EO?.forEach(t=>t.hostDisconnected?.())}attributeChangedCallback(t,e,i){this._$AK(t,i)}_$ET(t,e){const i=this.constructor.elementProperties.get(t),s=this.constructor._$Eu(t,i);if(void 0!==s&&!0===i.reflect){const r=(void 0!==i.converter?.toAttribute?i.converter:v).toAttribute(e,i.type);this._$Em=t,null==r?this.removeAttribute(s):this.setAttribute(s,r),this._$Em=null}}_$AK(t,e){const i=this.constructor,s=i._$Eh.get(t);if(void 0!==s&&this._$Em!==s){const t=i.getPropertyOptions(s),r="function"==typeof t.converter?{fromAttribute:t.converter}:void 0!==t.converter?.fromAttribute?t.converter:v;this._$Em=s;const a=r.fromAttribute(e,t.type);this[s]=a??this._$Ej?.get(s)??a,this._$Em=null}}requestUpdate(t,e,i,s=!1,r){if(void 0!==t){const a=this.constructor;if(!1===s&&(r=this[t]),i??=a.getPropertyOptions(t),!((i.hasChanged??y)(r,e)||i.useDefault&&i.reflect&&r===this._$Ej?.get(t)&&!this.hasAttribute(a._$Eu(t,i))))return;this.C(t,e,i)}!1===this.isUpdatePending&&(this._$ES=this._$EP())}C(t,e,{useDefault:i,reflect:s,wrapped:r},a){i&&!(this._$Ej??=new Map).has(t)&&(this._$Ej.set(t,a??e??this[t]),!0!==r||void 0!==a)||(this._$AL.has(t)||(this.hasUpdated||i||(e=void 0),this._$AL.set(t,e)),!0===s&&this._$Em!==t&&(this._$Eq??=new Set).add(t))}async _$EP(){this.isUpdatePending=!0;try{await this._$ES}catch(t){Promise.reject(t)}const t=this.scheduleUpdate();return null!=t&&await t,!this.isUpdatePending}scheduleUpdate(){return this.performUpdate()}performUpdate(){if(!this.isUpdatePending)return;if(!this.hasUpdated){if(this.renderRoot??=this.createRenderRoot(),this._$Ep){for(const[t,e]of this._$Ep)this[t]=e;this._$Ep=void 0}const t=this.constructor.elementProperties;if(t.size>0)for(const[e,i]of t){const{wrapped:t}=i,s=this[e];!0!==t||this._$AL.has(e)||void 0===s||this.C(e,void 0,i,s)}}let t=!1;const e=this._$AL;try{t=this.shouldUpdate(e),t?(this.willUpdate(e),this._$EO?.forEach(t=>t.hostUpdate?.()),this.update(e)):this._$EM()}catch(e){throw t=!1,this._$EM(),e}t&&this._$AE(e)}willUpdate(t){}_$AE(t){this._$EO?.forEach(t=>t.hostUpdated?.()),this.hasUpdated||(this.hasUpdated=!0,this.firstUpdated(t)),this.updated(t)}_$EM(){this._$AL=new Map,this.isUpdatePending=!1}get updateComplete(){return this.getUpdateComplete()}getUpdateComplete(){return this._$ES}shouldUpdate(t){return!0}update(t){this._$Eq&&=this._$Eq.forEach(t=>this._$ET(t,this[t])),this._$EM()}updated(t){}firstUpdated(t){}};b.elementStyles=[],b.shadowRootOptions={mode:"open"},b[m("elementProperties")]=new Map,b[m("finalized")]=new Map,f?.({ReactiveElement:b}),(_.reactiveElementVersions??=[]).push("2.1.2");const $=globalThis,w=t=>t,k=$.trustedTypes,S=k?k.createPolicy("lit-html",{createHTML:t=>t}):void 0,C="$lit$",E=`lit$${Math.random().toFixed(9).slice(2)}$`,z="?"+E,M=`<${z}>`,D=document,F=()=>D.createComment(""),I=t=>null===t||"object"!=typeof t&&"function"!=typeof t,T=Array.isArray,A="[ \t\n\f\r]",N=/<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g,R=/-->/g,O=/>/g,B=RegExp(`>|${A}(?:([^\\s"'>=/]+)(${A}*=${A}*(?:[^ \t\n\f\r"'\`<>=]|("|')|))|$)`,"g"),P=/'/g,L=/"/g,H=/^(?:script|style|textarea|title)$/i,U=t=>(e,...i)=>({_$litType$:t,strings:e,values:i}),W=U(1),j=U(2),G=Symbol.for("lit-noChange"),K=Symbol.for("lit-nothing"),V=new WeakMap,q=D.createTreeWalker(D,129);function Y(t,e){if(!T(t)||!t.hasOwnProperty("raw"))throw Error("invalid template strings array");return void 0!==S?S.createHTML(e):e}const X=(t,e)=>{const i=t.length-1,s=[];let r,a=2===e?"<svg>":3===e?"<math>":"",o=N;for(let e=0;e<i;e++){const i=t[e];let n,l,c=-1,d=0;for(;d<i.length&&(o.lastIndex=d,l=o.exec(i),null!==l);)d=o.lastIndex,o===N?"!--"===l[1]?o=R:void 0!==l[1]?o=O:void 0!==l[2]?(H.test(l[2])&&(r=RegExp("</"+l[2],"g")),o=B):void 0!==l[3]&&(o=B):o===B?">"===l[0]?(o=r??N,c=-1):void 0===l[1]?c=-2:(c=o.lastIndex-l[2].length,n=l[1],o=void 0===l[3]?B:'"'===l[3]?L:P):o===L||o===P?o=B:o===R||o===O?o=N:(o=B,r=void 0);const p=o===B&&t[e+1].startsWith("/>")?" ":"";a+=o===N?i+M:c>=0?(s.push(n),i.slice(0,c)+C+i.slice(c)+E+p):i+E+(-2===c?e:p)}return[Y(t,a+(t[i]||"<?>")+(2===e?"</svg>":3===e?"</math>":"")),s]};class Z{constructor({strings:t,_$litType$:e},i){let s;this.parts=[];let r=0,a=0;const o=t.length-1,n=this.parts,[l,c]=X(t,e);if(this.el=Z.createElement(l,i),q.currentNode=this.el.content,2===e||3===e){const t=this.el.content.firstChild;t.replaceWith(...t.childNodes)}for(;null!==(s=q.nextNode())&&n.length<o;){if(1===s.nodeType){if(s.hasAttributes())for(const t of s.getAttributeNames())if(t.endsWith(C)){const e=c[a++],i=s.getAttribute(t).split(E),o=/([.?@])?(.*)/.exec(e);n.push({type:1,index:r,name:o[2],strings:i,ctor:"."===o[1]?it:"?"===o[1]?st:"@"===o[1]?rt:et}),s.removeAttribute(t)}else t.startsWith(E)&&(n.push({type:6,index:r}),s.removeAttribute(t));if(H.test(s.tagName)){const t=s.textContent.split(E),e=t.length-1;if(e>0){s.textContent=k?k.emptyScript:"";for(let i=0;i<e;i++)s.append(t[i],F()),q.nextNode(),n.push({type:2,index:++r});s.append(t[e],F())}}}else if(8===s.nodeType)if(s.data===z)n.push({type:2,index:r});else{let t=-1;for(;-1!==(t=s.data.indexOf(E,t+1));)n.push({type:7,index:r}),t+=E.length-1}r++}}static createElement(t,e){const i=D.createElement("template");return i.innerHTML=t,i}}function J(t,e,i=t,s){if(e===G)return e;let r=void 0!==s?i._$Co?.[s]:i._$Cl;const a=I(e)?void 0:e._$litDirective$;return r?.constructor!==a&&(r?._$AO?.(!1),void 0===a?r=void 0:(r=new a(t),r._$AT(t,i,s)),void 0!==s?(i._$Co??=[])[s]=r:i._$Cl=r),void 0!==r&&(e=J(t,r._$AS(t,e.values),r,s)),e}class Q{constructor(t,e){this._$AV=[],this._$AN=void 0,this._$AD=t,this._$AM=e}get parentNode(){return this._$AM.parentNode}get _$AU(){return this._$AM._$AU}u(t){const{el:{content:e},parts:i}=this._$AD,s=(t?.creationScope??D).importNode(e,!0);q.currentNode=s;let r=q.nextNode(),a=0,o=0,n=i[0];for(;void 0!==n;){if(a===n.index){let e;2===n.type?e=new tt(r,r.nextSibling,this,t):1===n.type?e=new n.ctor(r,n.name,n.strings,this,t):6===n.type&&(e=new at(r,this,t)),this._$AV.push(e),n=i[++o]}a!==n?.index&&(r=q.nextNode(),a++)}return q.currentNode=D,s}p(t){let e=0;for(const i of this._$AV)void 0!==i&&(void 0!==i.strings?(i._$AI(t,i,e),e+=i.strings.length-2):i._$AI(t[e])),e++}}class tt{get _$AU(){return this._$AM?._$AU??this._$Cv}constructor(t,e,i,s){this.type=2,this._$AH=K,this._$AN=void 0,this._$AA=t,this._$AB=e,this._$AM=i,this.options=s,this._$Cv=s?.isConnected??!0}get parentNode(){let t=this._$AA.parentNode;const e=this._$AM;return void 0!==e&&11===t?.nodeType&&(t=e.parentNode),t}get startNode(){return this._$AA}get endNode(){return this._$AB}_$AI(t,e=this){t=J(this,t,e),I(t)?t===K||null==t||""===t?(this._$AH!==K&&this._$AR(),this._$AH=K):t!==this._$AH&&t!==G&&this._(t):void 0!==t._$litType$?this.$(t):void 0!==t.nodeType?this.T(t):(t=>T(t)||"function"==typeof t?.[Symbol.iterator])(t)?this.k(t):this._(t)}O(t){return this._$AA.parentNode.insertBefore(t,this._$AB)}T(t){this._$AH!==t&&(this._$AR(),this._$AH=this.O(t))}_(t){this._$AH!==K&&I(this._$AH)?this._$AA.nextSibling.data=t:this.T(D.createTextNode(t)),this._$AH=t}$(t){const{values:e,_$litType$:i}=t,s="number"==typeof i?this._$AC(t):(void 0===i.el&&(i.el=Z.createElement(Y(i.h,i.h[0]),this.options)),i);if(this._$AH?._$AD===s)this._$AH.p(e);else{const t=new Q(s,this),i=t.u(this.options);t.p(e),this.T(i),this._$AH=t}}_$AC(t){let e=V.get(t.strings);return void 0===e&&V.set(t.strings,e=new Z(t)),e}k(t){T(this._$AH)||(this._$AH=[],this._$AR());const e=this._$AH;let i,s=0;for(const r of t)s===e.length?e.push(i=new tt(this.O(F()),this.O(F()),this,this.options)):i=e[s],i._$AI(r),s++;s<e.length&&(this._$AR(i&&i._$AB.nextSibling,s),e.length=s)}_$AR(t=this._$AA.nextSibling,e){for(this._$AP?.(!1,!0,e);t!==this._$AB;){const e=w(t).nextSibling;w(t).remove(),t=e}}setConnected(t){void 0===this._$AM&&(this._$Cv=t,this._$AP?.(t))}}class et{get tagName(){return this.element.tagName}get _$AU(){return this._$AM._$AU}constructor(t,e,i,s,r){this.type=1,this._$AH=K,this._$AN=void 0,this.element=t,this.name=e,this._$AM=s,this.options=r,i.length>2||""!==i[0]||""!==i[1]?(this._$AH=Array(i.length-1).fill(new String),this.strings=i):this._$AH=K}_$AI(t,e=this,i,s){const r=this.strings;let a=!1;if(void 0===r)t=J(this,t,e,0),a=!I(t)||t!==this._$AH&&t!==G,a&&(this._$AH=t);else{const s=t;let o,n;for(t=r[0],o=0;o<r.length-1;o++)n=J(this,s[i+o],e,o),n===G&&(n=this._$AH[o]),a||=!I(n)||n!==this._$AH[o],n===K?t=K:t!==K&&(t+=(n??"")+r[o+1]),this._$AH[o]=n}a&&!s&&this.j(t)}j(t){t===K?this.element.removeAttribute(this.name):this.element.setAttribute(this.name,t??"")}}class it extends et{constructor(){super(...arguments),this.type=3}j(t){this.element[this.name]=t===K?void 0:t}}class st extends et{constructor(){super(...arguments),this.type=4}j(t){this.element.toggleAttribute(this.name,!!t&&t!==K)}}class rt extends et{constructor(t,e,i,s,r){super(t,e,i,s,r),this.type=5}_$AI(t,e=this){if((t=J(this,t,e,0)??K)===G)return;const i=this._$AH,s=t===K&&i!==K||t.capture!==i.capture||t.once!==i.once||t.passive!==i.passive,r=t!==K&&(i===K||s);s&&this.element.removeEventListener(this.name,this,i),r&&this.element.addEventListener(this.name,this,t),this._$AH=t}handleEvent(t){"function"==typeof this._$AH?this._$AH.call(this.options?.host??this.element,t):this._$AH.handleEvent(t)}}class at{constructor(t,e,i){this.element=t,this.type=6,this._$AN=void 0,this._$AM=e,this.options=i}get _$AU(){return this._$AM._$AU}_$AI(t){J(this,t)}}const ot=$.litHtmlPolyfillSupport;ot?.(Z,tt),($.litHtmlVersions??=[]).push("3.3.3");const nt=globalThis;let lt=class extends b{constructor(){super(...arguments),this.renderOptions={host:this},this._$Do=void 0}createRenderRoot(){const t=super.createRenderRoot();return this.renderOptions.renderBefore??=t.firstChild,t}update(t){const e=this.render();this.hasUpdated||(this.renderOptions.isConnected=this.isConnected),super.update(t),this._$Do=((t,e,i)=>{const s=i?.renderBefore??e;let r=s._$litPart$;if(void 0===r){const t=i?.renderBefore??null;s._$litPart$=r=new tt(e.insertBefore(F(),t),t,void 0,i??{})}return r._$AI(t),r})(e,this.renderRoot,this.renderOptions)}connectedCallback(){super.connectedCallback(),this._$Do?.setConnected(!0)}disconnectedCallback(){super.disconnectedCallback(),this._$Do?.setConnected(!1)}render(){return G}};lt._$litElement$=!0,lt.finalized=!0,nt.litElementHydrateSupport?.({LitElement:lt});const ct=nt.litElementPolyfillSupport;ct?.({LitElement:lt}),(nt.litElementVersions??=[]).push("4.2.2");const dt={solar:"#ff9800",gridImport:"#488fc2",gridExport:"#8353d1",batteryOut:"#4db6ac",battery:"#4db6ac",home:"#5BC8D8",ev:"#8DC892",inverter:"#96CAEE"},pt=["#FF8A65","#AED581","#CE93D8","#64B5F6","#ff9800","#96CAEE"];function ht(t){if(null==t||isNaN(t))return"— W";return Math.abs(t)>=1e3?`${(t/1e3).toFixed(1)} kW`:`${Math.round(t)} W`}function _t(t){const e=Math.abs(t);if(e<=0)return 4;const i=4-.9*Math.log10(Math.max(e,1));return Math.max(.5,Math.min(4,i))}function gt(t){if(!t)return"EUR";const e=t.states?.["sensor.sem_daily_costs"];return e?.attributes?.unit_of_measurement?e.attributes.unit_of_measurement:t.config?.currency||"EUR"}function ut(t,e,i){return`radial-gradient(ellipse 70% 60% at 50% 25%, ${e}${Math.round(.06*255).toString(16).padStart(2,"0")} 0%, transparent 100%),\n            radial-gradient(circle at 2px 2px, ${t.dotColor} 0.7px, transparent 0.7px)`}function ft(t,e){if(!t?.states)return"";const i=e||"sensor.sem_";return["pv1","pv2","pv3","pv4"].map(e=>t.states[`${i}pv_string_${e}_power`]?.state??"").join("|")}function mt(t,e){if(!t||!t.states)return[];const i=e||"sensor.sem_",s=[];for(const e of["pv1","pv2","pv3","pv4"]){const r=`${i}pv_string_${e}_power`,a=t.states[r];if(!a)continue;const o=parseFloat(a.state);if(isNaN(o))continue;const n=`${i}pv_string_${e}_daily_energy`,l=t.states[n],c=l?parseFloat(l.state):NaN;s.push({slot:e,watts:o,entityId:r,energyKwh:isNaN(c)?null:c,energyEntityId:l?n:null})}return s.length>=2?s:[]}const vt="\n    .pv-strings-row {\n        display: flex;\n        flex-wrap: wrap;\n        gap: 6px;\n        padding: 6px 12px;\n        font-family: 'Segoe UI','Roboto',sans-serif;\n        font-size: 12px;\n    }\n    .pv-chip {\n        display: inline-flex;\n        align-items: baseline;\n        gap: 4px;\n        padding: 2px 8px;\n        background: rgba(255, 152, 0, 0.10);\n        border: 1px solid rgba(255, 152, 0, 0.25);\n        border-radius: 999px;\n        color: var(--secondary-text-color, #aaa);\n        cursor: pointer;\n        transition: background 120ms ease;\n    }\n    .pv-chip:hover { background: rgba(255, 152, 0, 0.18); }\n    .pv-chip-label {\n        font-size: 10px;\n        letter-spacing: 0.5px;\n        text-transform: uppercase;\n        opacity: 0.7;\n    }\n    .pv-chip-value {\n        color: var(--sem-solar, #ff9800);\n        font-weight: 600;\n        font-variant-numeric: tabular-nums;\n    }\n";function yt(t,e,i){customElements.get(t)||(customElements.define(t,e),i&&(window.customCards=window.customCards||[],window.customCards.push(i)))}class xt extends lt{constructor(){super(),this._hass=null,this._config=null,this._lang=null,this._localizeReady=!1,this._prevVals={},this._frozenEntities={},this._holdTimers={},this._holdIntervals={},this._cachedTheme=null,this._updateTimer=null}set hass(t){this._hass,this._hass=t;const e=t?.language,i="function"==typeof semLocalize;let s=!1;if((e!==this._lang||i&&!this._localizeReady)&&(this._lang=e,this._localizeReady=i,s=!0),this._isFrozen()&&!s)return;const r=this.constructor.watchedEntities||[];if(r.length>0&&!s){const e=t.states[r[0]]?.state;if("unavailable"===e||"unknown"===e)return}let a=!1;for(const e of r){const i=t.states[e]?.state;if(this._prevVals[e]!==i){a=!0;break}}if(a||s){for(const e of r)this._prevVals[e]=t.states[e]?.state;this._scheduleUpdate()}}get hass(){return this._hass}_scheduleUpdate(){this._updateTimer||(this._updateTimer=setTimeout(()=>{this._updateTimer=null,this.requestUpdate()},16))}_theme(){const t=getComputedStyle(document.documentElement).getPropertyValue("--primary-background-color").trim();return this._cachedTheme&&this._cachedThemeKey===t||(this._cachedThemeKey=t,this._cachedTheme=function(){const t=document.documentElement,e=getComputedStyle(t),i=(t,i)=>e.getPropertyValue(t).trim()||i,s=i("--primary-text-color","#e0e0e0"),r=i("--secondary-text-color","#888888"),a=i("--card-background-color","rgba(30,35,45,0.5)"),o=i("--divider-color","rgba(255,255,255,0.12)"),n=i("--secondary-background-color","rgba(255,255,255,0.06)"),l=i("--ha-card-box-shadow","0 2px 8px rgba(0,0,0,0.15)"),c=i("--primary-color","#42a5f5"),d=(()=>{const t=i("--primary-background-color","#111"),e=t.match(/\d+/g);return e&&e.length>=3?(.299*+e[0]+.587*+e[1]+.114*+e[2])/255<.5:!(t.startsWith("#f")||t.startsWith("#e")||t.startsWith("#d")||t.startsWith("#c")||t.startsWith("rgb(2"))})();return{text:s,textSec:r,cardBg:a,divider:o,bgSec:n,shadow:l,accent:c,isDark:d,textTertiary:d?"rgba(255,255,255,0.45)":"rgba(0,0,0,0.50)",textDisabled:d?"rgba(255,255,255,0.26)":"rgba(0,0,0,0.30)",surface:d?"rgba(255,255,255,0.06)":"rgba(0,0,0,0.03)",surfaceHover:d?"rgba(255,255,255,0.10)":"rgba(0,0,0,0.06)",surfaceBorder:d?"rgba(255,255,255,0.12)":"rgba(0,0,0,0.08)",dotColor:d?"rgba(128,128,128,0.05)":"rgba(128,128,128,0.06)",glowAlpha:d?.05:.03,tooltipBg:d?"rgba(20,20,30,0.95)":"rgba(255,255,255,0.95)",tooltipText:d?"#e0e0e0":"#333333",tooltipBorder:d?"rgba(255,255,255,0.15)":"rgba(0,0,0,0.12)"}}()),this._cachedTheme}_t(t){return t?"function"==typeof semLocalize?semLocalize(t,this._hass?.language):t:""}_state(t,e=0){const i=this._frozenEntities[t];if(i)return i.value;const s=this._hass?.states[t];return s&&"unavailable"!==s.state&&"unknown"!==s.state?parseFloat(s.state)??e:e}_stateStr(t){const e=this._frozenEntities[t];if(e)return String(e.value);const i=this._hass?.states[t];return i&&"unavailable"!==i.state&&"unknown"!==i.state?i.state:""}_pcEntity(t,e,i){const s=this._hass?.states||{},r=new RegExp(`^${t}\\.sem_charger_.+_${e}$`);let a=Object.keys(s).filter(t=>r.test(t));return"night_charging"===e&&(a=a.filter(t=>!t.endsWith("_smart_night_charging"))),a.sort(),a.length?a[0]:i}_stateAttrs(t){return this._hass?.states[t]?.attributes||{}}_freezeEntity(t,e){const i=this._frozenEntities[t];i?.timer&&clearTimeout(i.timer),this._frozenEntities[t]={value:e,timer:setTimeout(()=>{delete this._frozenEntities[t],this.requestUpdate()},1500)}}_isFrozen(){return Object.keys(this._frozenEntities).length>0}async _callService(t,e,i){if(this._hass)try{await this._hass.callService(t,e,i)}catch(t){console.error(`[SEM ${this.tagName}]`,t)}}_setNumber(t,e){const i=this._hass?.states[t];if(!i)return;const s=parseFloat(i.attributes.min)||0,r=parseFloat(i.attributes.max)||100,a=Math.max(s,Math.min(r,e));this._freezeEntity(t,a),this.requestUpdate(),this._callService("number","set_value",{entity_id:t,value:a})}_stepNumber(t,e){const i=this._hass?.states[t];if(!i)return;const s=this._frozenEntities[t],r=s?s.value:parseFloat(i.state)||0,a=parseFloat(i.attributes.step)||1;this._setNumber(t,r+e*a)}_toggleSwitch(t){const e=this._hass?.states[t];if(!e)return;const i="on"===e.state?"off":"on";this._freezeEntity(t,i),this.requestUpdate();const s="on"===e.state?"turn_off":"turn_on";this._callService("switch",s,{entity_id:t})}_selectOption(t,e){this._freezeEntity(t,e),this.requestUpdate(),this._callService("select","select_option",{entity_id:t,option:e})}_startHold(t,e){this._stopHold(t),this._holdTimers[t]=setTimeout(()=>{this._holdIntervals[t]=setInterval(()=>{this._stepNumber(t,e)},150)},400)}_stopHold(t){clearTimeout(this._holdTimers[t]),clearInterval(this._holdIntervals[t]),delete this._holdTimers[t],delete this._holdIntervals[t]}updated(){if(window._semDebug){this.style.outline="2px solid red",this.style.outlineOffset="-2px",clearTimeout(this._debugFlashTimer),this._debugFlashTimer=setTimeout(()=>{this.style.outline="",this.style.outlineOffset=""},200);const t=this.tagName.toLowerCase();window._semRenderLog||(window._semRenderLog={}),window._semRenderLog[t]=(window._semRenderLog[t]||0)+1}}connectedCallback(){super.connectedCallback(),window._semDebug&&console.log(`[SEM DEBUG] ${this.tagName} connectedCallback`),this._localizeReady||"function"==typeof semLocalize?"function"==typeof semLocalize&&(this._localizeReady=!0):(this._onLocalizeReady=()=>{document.removeEventListener("sem-localize-ready",this._onLocalizeReady),this._onLocalizeReady=null,this._localizeReady=!0,this._hass&&this.requestUpdate()},document.addEventListener("sem-localize-ready",this._onLocalizeReady))}disconnectedCallback(){super.disconnectedCallback(),window._semDebug&&console.log(`[SEM DEBUG] ${this.tagName} disconnectedCallback !!!`),this._onLocalizeReady&&(document.removeEventListener("sem-localize-ready",this._onLocalizeReady),this._onLocalizeReady=null),this._updateTimer&&(clearTimeout(this._updateTimer),this._updateTimer=null);for(const t of Object.keys(this._holdTimers))this._stopHold(t);for(const t of Object.keys(this._frozenEntities))clearTimeout(this._frozenEntities[t]?.timer);this._frozenEntities={}}setConfig(t){this._config=t}getCardSize(){return 4}static getStubConfig(){return{}}}yt("sem-title-card",class extends xt{static get watchedEntities(){return[]}constructor(){super(),this._renderedSubtitle=null,this._templateUnsub=null,this._templateSubbed=!1}setConfig(t){super.setConfig(t),this._unsubTemplate(),this._templateSubbed=!1,this._renderedSubtitle=null}_hasJinja(t){return t&&(t.includes("{%")||t.includes("{{"))}set hass(t){this._hass,this._hass=t;const e=t?.language,i="function"==typeof semLocalize;(e!==this._lang||i&&!this._localizeReady)&&(this._lang=e,this._localizeReady=i,this.requestUpdate()),this._hasJinja(this._config?.subtitle)&&!this._templateSubbed&&this._subscribeTemplate()}_subscribeTemplate(){if(!this._hass?.connection||this._templateSubbed)return;this._templateSubbed=!0;const t=this._config.subtitle;this._hass.connection.subscribeMessage(t=>{const e=t.result;e!==this._renderedSubtitle&&(this._renderedSubtitle=e,this.requestUpdate())},{type:"render_template",template:t,variables:{}}).then(t=>{this._templateUnsub=t}).catch(()=>{this._renderedSubtitle=this._config.subtitle,this.requestUpdate()})}_unsubTemplate(){this._templateUnsub&&(this._templateUnsub(),this._templateUnsub=null)}disconnectedCallback(){super.disconnectedCallback(),this._unsubTemplate()}render(){if(!this._config)return K;const t=this._t(this._config.title_key||this._config.title||"");let e="";e=this._hasJinja(this._config.subtitle)?this._renderedSubtitle||"":this._t(this._config.subtitle||"");const i=this._theme();return W`
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
                <div class="title">${t}</div>
                ${e?W`<div class="subtitle">${e}</div>`:K}
                <div class="divider"></div>
            </div>
        `}getCardSize(){return 1}static getStubConfig(){return{title:"Section Title"}}},{type:"sem-title-card",name:"SEM Title Card",description:"Runtime-translated section header for SEM dashboard"});const bt=(t,e)=>"function"==typeof semLocalize?semLocalize(t,e?.language):t,$t={home:{titleKey:"home",subtitleKey:"home_sub",color:"#5BC8D8",icon:()=>j`
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
            <line x1="-16" y1="8" x2="16" y2="8" stroke-width="1" opacity="0.3"/>`}};yt("sem-tab-header",class extends xt{static get watchedEntities(){return[]}constructor(){super(),this._tab="home",this._prefix="sensor.sem_",this._responsiveApplied=!1,this._lastStatsKey=""}connectedCallback(){super.connectedCallback(),this._applyResponsiveContainer()}_applyResponsiveContainer(){this._responsiveApplied||requestAnimationFrame(()=>{let t=this;for(;t;){const e=t.getRootNode()?.host;if(!e)break;if("HUI-VERTICAL-STACK-CARD"===e.tagName){const t=e.parentElement;if(t&&"HUI-CARD"===t.tagName)return t.style.maxWidth="900px",t.style.margin="0 auto",t.style.display="block",void(this._responsiveApplied=!0)}t=e}})}setConfig(t){super.setConfig(t),this._tab=t.tab||"home",this._prefix=t.entity_prefix||"sensor.sem_"}set hass(t){this._hass,this._hass=t;const e=t?.language,i="function"==typeof semLocalize;let s=!1;if((e!==this._lang||i&&!this._localizeReady)&&(this._lang=e,this._localizeReady=i,s=!0),this._isFrozen()&&!s)return;const r=this._buildStatsKey(t);(r!==this._lastStatsKey||s)&&(this._lastStatsKey=r,this.requestUpdate()),this._responsiveApplied||this._applyResponsiveContainer()}_buildStatsKey(t){if(!t)return"";const e=e=>t.states[`${this._prefix}${e}`]?.state||"",i=this._tab;return"home"===i?[e("solar_power"),e("autarky_rate"),e("self_consumption_rate"),e("daily_solar_energy")].join(","):"energy"===i?[e("daily_solar_energy"),e("daily_home_energy"),e("self_consumption_rate")].join(","):"battery"===i?[e("battery_soc"),e("battery_power"),e("battery_health_score")].join(","):"ev"===i?[e("ev_power"),e("daily_ev_energy"),e("charging_state")].join(","):"control"===i?[e("target_peak_limit"),e("controllable_devices_count"),e("surplus_active_devices")].join(","):"config"===i?[e("charging_state"),e("heat_pump_registered"),e("battery_status")].join(","):"costs"===i?[e("daily_costs"),e("daily_savings"),e("daily_net_cost")].join(","):"system"===i?[e("energy_optimization_score"),e("lifetime_total_savings"),e("lifetime_co2_avoided")].join(","):""}_getState(t,e=0){const i=this._hass?.states[`${this._prefix}${t}`];return i&&"unavailable"!==i.state&&"unknown"!==i.state?parseFloat(i.state)??e:e}_getStatLabels(){const t=t=>bt(t,this._hass),e=this._tab;return"home"===e?[t("solar"),t("autarky"),t("self_use"),t("today")]:"energy"===e?[t("solar"),t("home"),t("self_use")]:"battery"===e?[t("soc"),t("power"),t("health")]:"ev"===e?[t("power"),t("today"),t("session")]:"control"===e?[t("peak"),t("devices"),t("active")]:"config"===e?[t("config_stat_chargers"),t("config_stat_heatpump"),t("config_stat_battery")]:"costs"===e?[t("cost"),t("saved"),t("net")]:"system"===e?[t("score"),t("saved"),t("co2")]:["—","—","—"]}_getStatValues(){const t=this._tab,e=gt(this._hass)||"EUR";if("home"===t)return[ht(this._getState("solar_power",0)),this._getState("autarky_rate",0).toFixed(0)+"%",this._getState("self_consumption_rate",0).toFixed(0)+"%",this._getState("daily_solar_energy",0).toFixed(1)+" kWh"];if("energy"===t)return[this._getState("daily_solar_energy",0).toFixed(1)+" kWh",this._getState("daily_home_energy",0).toFixed(1)+" kWh",this._getState("self_consumption_rate",0).toFixed(0)+"%"];if("battery"===t)return[this._getState("battery_soc",0).toFixed(0)+"%",ht(this._getState("battery_power",0)),this._getState("battery_health_score",100).toFixed(0)+"%"];if("ev"===t)return[ht(this._getState("ev_power",0)),this._getState("daily_ev_energy",0).toFixed(1)+" kWh",this._getState("session_energy",0).toFixed(1)+" kWh"];if("control"===t)return[this._getState("target_peak_limit",5).toFixed(1)+" kW",this._getState("controllable_devices_count",0).toFixed(0),this._getState("surplus_active_devices",0).toFixed(0)];if("config"===t){const t=t=>bt(t,this._hass),e=Object.keys(this._hass?.states||{}).filter(t=>t.match(/^number\.sem_charger_.+_minimum_current$/)).length,i="on"===this._hass?.states[`${this._prefix}heat_pump_registered`]?.state,s=this._hass?.states[`${this._prefix}battery_soc`];return[String(e),t(i?"on":"off"),s?Math.round(parseFloat(s.state)||0)+"%":"—"]}return"costs"===t?[this._getState("daily_costs",0).toFixed(2)+" "+e,this._getState("daily_savings",0).toFixed(2)+" "+e,this._getState("daily_net_cost",0).toFixed(2)+" "+e]:"system"===t?[this._getState("energy_optimization_score",0).toFixed(0),this._getState("lifetime_total_savings",0).toFixed(0)+" "+e,this._getState("lifetime_co2_avoided",0).toFixed(0)+" kg"]:["—","—","—"]}render(){if(!this._hass||!this._config)return K;const t=$t[this._tab]||$t.home,e=this._config.title||bt(t.titleKey,this._hass),i=this._config.subtitle||bt(t.subtitleKey,this._hass),s=t.color,r=this._getStatLabels(),a=this._getStatValues(),o=this._theme(),n=o.isDark?s:`color-mix(in srgb, ${s} 65%, black)`,l=o.isDark?`0 0 12px ${s}40`:"none",c=o.isDark?.3:.18;return W`
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
                .title-area { flex: 1; min-width: 0; }
                .tab-title {
                    font-size: 20px; font-weight: 700; color: ${n};
                    letter-spacing: 0.5px; text-shadow: ${l};
                }
                .tab-subtitle {
                    font-size: 12px; color: var(--secondary-text-color, ${o.textSec});
                    margin-top: 2px; font-weight: 500;
                }
                .stats { display: flex; gap: 16px; flex-shrink: 0; }
                .stat { text-align: center; min-width: 50px; }
                .stat-value {
                    font-size: 15px; font-weight: 700; font-variant-numeric: tabular-nums;
                    color: var(--primary-text-color, ${o.text});
                }
                .stat-label {
                    font-size: 10px; color: var(--secondary-text-color, ${o.textTertiary});
                    font-weight: 500; margin-top: 1px;
                }
                @media (max-width: 500px) {
                    .header-wrap { padding: 12px 14px; gap: 12px; }
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
                                ${t.icon()}
                            </g>
                        </svg>
                    </div>
                    <div class="title-area">
                        <div class="tab-title">${e}</div>
                        <div class="tab-subtitle">${i}</div>
                    </div>
                    <div class="stats">
                        ${r.map((t,e)=>W`
                            <div class="stat">
                                <div class="stat-value">${a[e]}</div>
                                <div class="stat-label">${t}</div>
                            </div>
                        `)}
                    </div>
                </div>
            </ha-card>
        `}getCardSize(){return 1}static getStubConfig(){return{tab:"home"}}},{type:"sem-tab-header",name:"SEM Tab Header",description:"Lumina-styled tab header with glow icon and live stats"});const wt={"clear-night":{icon:"🌙",key:"weather_clear"},cloudy:{icon:"☁️",key:"weather_cloudy"},fog:{icon:"🌫️",key:"weather_fog"},hail:{icon:"🧊",key:"weather_hail"},lightning:{icon:"⚡",key:"weather_thunder"},"lightning-rainy":{icon:"⛈️",key:"weather_thunderstorm"},partlycloudy:{icon:"⛅",key:"weather_partly_cloudy"},pouring:{icon:"🌧️",key:"weather_pouring"},rainy:{icon:"🌦️",key:"weather_rain"},snowy:{icon:"❄️",key:"weather_snow"},"snowy-rainy":{icon:"🌨️",key:"weather_sleet"},sunny:{icon:"☀️",key:"weather_sunny"},windy:{icon:"💨",key:"weather_windy"},"windy-variant":{icon:"💨",key:"weather_windy"},exceptional:{icon:"⚠️",key:"weather_exceptional"}};yt("sem-weather-card",class extends xt{constructor(){super(),this._clockTime="--:--",this._clockDate="",this._clockInterval=null}static get watchedEntities(){return[]}setConfig(t){if(!t.entity)throw new Error("sem-weather-card requires entity");super.setConfig(t)}set hass(t){this._hass,this._hass=t;const e=t?.language,i="function"==typeof semLocalize;let s=!1;if((e!==this._lang||i&&!this._localizeReady)&&(this._lang=e,this._localizeReady=i,s=!0),this._isFrozen()&&!s)return;const r=this._config?.entity;if(!r)return;const a=t?.states[r],o=(a?.state||"")+JSON.stringify(a?.attributes?.forecast?.[0]||"")+"|"+(e||"");(o!==this._lastWeatherKey||s)&&(this._lastWeatherKey=o,this.requestUpdate())}get hass(){return this._hass}connectedCallback(){super.connectedCallback(),this._updateClock(),this._clockInterval=setInterval(()=>{this._updateClock()},3e4)}disconnectedCallback(){super.disconnectedCallback(),this._clockInterval&&(clearInterval(this._clockInterval),this._clockInterval=null)}_updateClock(){const t=new Date,e=this._hass?.language||navigator.language||"en";this._clockTime=t.toLocaleTimeString(e,{hour:"2-digit",minute:"2-digit"}),this._clockDate=t.toLocaleDateString(e,{weekday:"long",day:"numeric",month:"long",year:"numeric"}),this.requestUpdate()}_renderForecastRows(t,e){const i=this._hass?.language||navigator.language||"en";return t.slice(0,e).map(t=>{const e=new Date(t.datetime).toLocaleDateString(i,{weekday:"short"}),s=wt[t.condition]?.icon||"❓",r=null!=t.templow?Math.round(t.templow):"—",a=null!=t.temperature?Math.round(t.temperature):"—",o="number"==typeof a&&"number"==typeof r?a-r:0,n=Math.max(o/30*100,10),l="number"==typeof a&&"number"==typeof r?(r+a)/2:15,c=Math.min(Math.max((l-0)/30,0),1),d=c>.5?`rgba(255,${Math.round(200-100*c)},0,0.6)`:`rgba(${Math.round(100+200*c)},${Math.round(180+40*c)},255,0.5)`;return W`
                <div class="forecast-row">
                    <span class="f-day">${e}</span>
                    <span class="f-icon">${s}</span>
                    <span class="f-low">${r}°</span>
                    <div class="f-bar-wrap">
                        <div class="f-bar" style="width:${n}%;background:${d}"></div>
                    </div>
                    <span class="f-high">${a}°</span>
                </div>
            `})}render(){if(!this._config)return K;const t=this._config.entity,e=this._config.forecast_rows||5,i=this._hass?.states[t];if(!i)return W`
                <ha-card>
                    <div style="padding:16px;color:#ef5350">Entity ${t} not found</div>
                </ha-card>
            `;const s=this._theme(),r=i.state,a=i.attributes,o=null!=a.temperature?Math.round(a.temperature):"—",n=a.temperature_unit||"°C",l=null!=a.humidity?Math.round(a.humidity):"—",c=null!=a.wind_speed?Math.round(a.wind_speed):"—",d=a.wind_speed_unit||"km/h",p=wt[r]||{icon:"❓",key:""},h=a.forecast||[];return W`
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
                        ${h.length?this._renderForecastRows(h,e):K}
                    </div>
                </div>
            </ha-card>
        `}getCardSize(){return 5}static getStubConfig(){return{entity:"weather.home"}}},{type:"custom:sem-weather-card",name:"SEM Weather",description:"Lumina-styled clock + weather card with forecast",preview:!1});const kt=[{key:"today",labelKey:"period_today"},{key:"yesterday",labelKey:"period_yesterday"},{key:"week",labelKey:"period_this_week"},{key:"month",labelKey:"period_this_month"},{key:"year",labelKey:"period_this_year"}];yt("sem-period-selector-card",class extends xt{static get watchedEntities(){return[]}constructor(){super(),this._active="week",this._firstRender=!0}setConfig(t){super.setConfig(t),t.default_period&&(this._active=t.default_period)}set hass(t){this._hass,this._hass=t;const e=t?.language,i="function"==typeof semLocalize;(e!==this._lang||i&&!this._localizeReady)&&(this._lang=e,this._localizeReady=i,this.requestUpdate())}get hass(){return this._hass}firstUpdated(){this._dispatchPeriod(this._active)}_getPeriod(t){const e=new Date,i=(t=>new Date(t.getFullYear(),t.getMonth(),t.getDate()))(e);switch(t){case"today":return{start:i,end:e,granularity:"hour"};case"yesterday":{const t=new Date(i);return t.setDate(t.getDate()-1),{start:t,end:i,granularity:"hour"}}case"week":{const t=e.getDay()||7,s=new Date(i);return s.setDate(s.getDate()-(t-1)),{start:s,end:e,granularity:"day"}}case"month":return{start:new Date(e.getFullYear(),e.getMonth(),1),end:e,granularity:"day"};case"year":return{start:new Date(e.getFullYear(),0,1),end:e,granularity:"month"};default:return this._getPeriod("week")}}_dispatchPeriod(t){this._active=t,this.requestUpdate();const e=this._getPeriod(t);document.dispatchEvent(new CustomEvent("sem-period-change",{detail:{...e,key:t}}))}render(){if(!this._config)return K;const t=this._theme();return W`
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
                        radial-gradient(circle at 2px 2px, ${t.dotColor} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                }
                .btn {
                    border: 1px solid var(--divider-color, ${t.surfaceBorder});
                    background: var(--secondary-background-color, ${t.surface});
                    color: var(--secondary-text-color, ${t.textSec});
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
                    background: var(--secondary-background-color, ${t.surfaceHover});
                    color: var(--primary-text-color, ${t.text});
                    border-color: var(--divider-color, ${t.surfaceBorder});
                }
                .btn.active {
                    background: rgba(66,165,245,0.18);
                    border-color: rgba(66,165,245,0.40);
                    color: ${t.accent};
                    box-shadow: 0 0 16px rgba(66,165,245,0.12), 0 0 4px rgba(66,165,245,0.08);
                    font-weight: 600;
                }
            </style>
            <ha-card>
                <div class="sem-period">
                    ${kt.map(t=>W`
                        <button
                            class="btn ${this._active===t.key?"active":""}"
                            role="button"
                            aria-label=${this._t(t.labelKey)}
                            aria-pressed=${this._active===t.key}
                            @click=${()=>this._dispatchPeriod(t.key)}
                        >${this._t(t.labelKey)}</button>
                    `)}
                </div>
            </ha-card>
        `}getCardSize(){return 1}static getStubConfig(){return{}}},{type:"custom:sem-period-selector-card",name:"SEM Period Selector",description:"Glassmorphism period picker for SEM chart cards",preview:!1});const St="sensor.sem_",Ct=["flow_solar_to_home_energy","flow_solar_to_ev_energy","daily_co2_avoided","yearly_co2_avoided","lifetime_co2_avoided","yearly_trees_equivalent","lifetime_trees_equivalent"];function Et(t){return Ct.map(e=>`${t}${e}`)}yt("sem-energy-impact-card",class extends xt{static get watchedEntities(){return Et(St)}setConfig(t){super.setConfig(t),this._prefix=t.entity_prefix||St,this._prefix!==St&&(this._prevVals={})}set hass(t){this._hass,this._hass=t;const e=t?.language,i="function"==typeof semLocalize;let s=!1;if((e!==this._lang||i&&!this._localizeReady)&&(this._lang=e,this._localizeReady=i,s=!0),this._isFrozen()&&!s)return;const r=Et(this._prefix||St);let a=!1;for(const e of r)if(this._prevVals[e]!==t.states[e]?.state){a=!0;break}if(a||s){for(const e of r)this._prevVals[e]=t.states[e]?.state;this._scheduleUpdate()}}get hass(){return this._hass}_val(t,e=0){return this._state(`${this._prefix||St}${t}`,e)}_treeIcon(t){return t>=50?"mdi:forest":t>=10?"mdi:pine-tree":t>=1?"mdi:tree":"mdi:sprout"}render(){if(!this._config)return K;const t=this._theme(),e=this._val("flow_solar_to_home_energy")+this._val("flow_solar_to_ev_energy"),i=(.128*e).toFixed(1),s=`${e.toFixed(1)} kWh × 128 g/kWh`,r=this._val("yearly_trees_equivalent"),a=this._val("lifetime_trees_equivalent"),o=this._val("yearly_co2_avoided"),n=this._val("lifetime_co2_avoided"),l=r>=10?r.toFixed(0):r.toFixed(1),c=this._treeIcon(r);return W`
            <style>
                :host { display: block; }

                .wrap {
                    padding: 16px;
                    background:
                        radial-gradient(ellipse 70% 60% at 50% 25%, rgba(255,152,0,0.06) 0%, transparent 100%),
                        radial-gradient(circle at 2px 2px, ${t.dotColor} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI', 'Roboto', sans-serif;
                    color: var(--primary-text-color, ${t.text});
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
                    background: ${t.surface};
                    border: 1px solid ${t.surfaceBorder};
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
                    color: var(--secondary-text-color, ${t.textSec});
                }

                .tile-hero {
                    font-size: 22px;
                    font-weight: 700;
                    font-variant-numeric: tabular-nums;
                    line-height: 1.1;
                }

                .tile-detail {
                    font-size: 12px;
                    color: var(--secondary-text-color, ${t.textSec});
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
                    color: var(--secondary-text-color, ${t.textSec});
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
        `}getCardSize(){return 3}static getStubConfig(){return{entity_prefix:St}}},{type:"custom:sem-energy-impact-card",name:"SEM Energy Impact Card",description:"Environmental impact display for Solar Energy Management",preview:!1});const zt="daily_ev_energy",Mt="lifetime_ev_energy",Dt="lifetime_ev_solar_share",Ft="lifetime_ev_cost",It="lifetime_ev_sessions",Tt="sensor.sem_";yt("sem-ev-progress-card",class extends xt{static get watchedEntities(){return[`${Tt}${zt}`,`${Tt}${Mt}`,`${Tt}${Dt}`,`${Tt}${Ft}`,`${Tt}${It}`,"number.sem_daily_ev_target","number.sem_charger_ev_charger_daily_ev_target"]}_evDailyTarget(){const t=this._hass?.states||{},e=Object.keys(t).filter(t=>/^number\.sem_charger_.+_daily_ev_target$/.test(t)).sort();if(e.length){const i=parseFloat(t[e[0]]?.state);if(!isNaN(i))return i}return this._state("number.sem_daily_ev_target",10)}setConfig(t){super.setConfig(t)}_prefix(){return this._config?.entity_prefix??Tt}_pct(t,e){return e<=0?0:Math.min(100,t/e*100)}_barColor(t,e){return 0===t?"#666":e>=100?"#8DC892":e>=70?"#ff9800":"#f44336"}_fmtEnergy(t){return null==t||isNaN(t)?"—":t.toFixed(t<10?2:1)+" kWh"}_fmtCost(t,e){return null==t||isNaN(t)?"—":t.toFixed(2)+" "+e}_fmtSessions(t){return null==t||isNaN(t)?"—":String(Math.round(t))}render(){if(!this._hass||!this._config)return K;const t=this._theme(),e=this._prefix(),i=this._state(`${e}${zt}`),s=this._evDailyTarget(),r=this._state(`${e}${Mt}`),a=this._state(`${e}${Dt}`),o=this._state(`${e}${Ft}`),n=this._state(`${e}${It}`),l=gt(this._hass),c=this._pct(i,s),d=this._barColor(s,c),p=s>0?W`<span class="target-pct">${Math.round(c)}% ${this._t("of_target")}</span>`:W`<span class="target-pct no-target">${this._t("no_target")}</span>`,h=["radial-gradient(ellipse 80% 70% at 20% 50%, rgba(141,200,146,0.06) 0%, transparent 70%)",`radial-gradient(circle at 2px 2px, ${t.dotColor} 0.7px, transparent 0.7px)`].join(", ");return W`
            <style>
                :host {
                    display: block;
                    font-family: 'Segoe UI', 'Roboto', sans-serif;
                }

                .card {
                    background: ${t.cardBg};
                    background-image: ${h};
                    background-size: auto, 16px 16px;
                    border-radius: 12px;
                    padding: 16px;
                    box-shadow: ${t.shadow};
                    color: ${t.text};
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
                    color: ${t.text};
                    letter-spacing: 0.3px;
                }

                .progress-values {
                    font-size: 12px;
                    color: ${t.textSec};
                    margin-top: 2px;
                }

                .target-pct {
                    font-size: 11px;
                    color: ${t.textSec};
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
                    background: ${t.surface};
                    border: 1px solid ${t.surfaceBorder};
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
                    background: ${t.divider};
                    margin: 14px 0;
                }

                /* ── Lifetime stats section ── */
                .lifetime-label {
                    font-size: 11px;
                    font-weight: 600;
                    text-transform: uppercase;
                    letter-spacing: 1px;
                    color: ${t.textSec};
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
                    background: ${t.surface};
                    border: 1px solid ${t.surfaceBorder};
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
                    color: ${t.text};
                    line-height: 1.2;
                }

                .stat-label {
                    font-size: 10px;
                    color: ${t.textSec};
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
        `}getCardSize(){return 3}static getStubConfig(){return{entity_prefix:Tt}}},{type:"sem-ev-progress-card",name:"SEM EV Progress Card",description:"Daily EV progress bar and lifetime charging statistics"});yt("sem-gauge-card",class extends xt{static get watchedEntities(){return[]}setConfig(t){if(!t.entity)throw new Error("sem-gauge-card requires entity");super.setConfig(t),this._entity=t.entity,this._name=t.name||null,this._min=t.min??0,this._max=t.max??100,this._color=t.color||"#4db6ac",this._unit=t.unit||"%"}set hass(t){this._hass,this._hass=t;const e=t?.states[this._entity]?.state;e!==this._lastState&&(this._lastState=e,this.requestUpdate())}get hass(){return this._hass}render(){if(!this._hass||!this._config)return K;const t=this._hass.states[this._entity],e=t&&parseFloat(t.state)||0,i=this._name||t?.attributes?.friendly_name||this._entity,s=Math.min(Math.max((e-this._min)/(this._max-this._min),0),1),r=this._theme(),a=this._color,o=58,n=-210,l=n+240*s,c=t=>{const e=t*Math.PI/180;return{x:70+o*Math.cos(e),y:70+o*Math.sin(e)}},d=c(n),p=c(30),h=c(l),_=240*s>180?1:0,g=s<.5?`color-mix(in srgb, #f44336 ${Math.round(100*(1-2*s))}%, #ff9800)`:`color-mix(in srgb, ${a} ${Math.round(2*(s-.5)*100)}%, #ff9800)`;return W`
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
                        <span class="gauge-value" style="color:${g}">${e.toFixed(1)}${this._unit}</span>
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
        `}getCardSize(){return 3}static getStubConfig(){return{entity:"sensor.sem_self_consumption_rate"}}},{type:"custom:sem-gauge-card",name:"SEM Gauge Card",description:"Lumina-styled arc gauge for percentage values",preview:!1});const At="sensor.sem_",Nt=["solar_power","daily_solar_energy","monthly_solar_yield_energy","yearly_solar_yield_energy","flow_solar_to_home_power","flow_solar_to_battery_power","flow_solar_to_ev_power","flow_solar_to_grid_power","flow_solar_to_home_energy","flow_solar_to_battery_energy","flow_solar_to_ev_energy","flow_solar_to_grid_energy","forecast_today_kwh","forecast_tomorrow_kwh","forecast_remaining_today_kwh","forecast_peak_power_today_w","forecast_peak_time_today","best_surplus_window","pv_daily_specific_yield","pv_performance_vs_forecast","pv_estimated_annual_degradation","pv_degradation_trend","pv_string_pv1_power","pv_string_pv1_daily_energy","pv_string_pv2_power","pv_string_pv2_daily_energy","pv_string_pv3_power","pv_string_pv3_daily_energy","pv_string_pv4_power","pv_string_pv4_daily_energy"];function Rt(t){return Nt.map(e=>`${t}${e}`)}yt("sem-solar-card",class extends xt{static get watchedEntities(){return Rt(At)}setConfig(t){super.setConfig(t),this._prefix=t.entity_prefix||At,this._prefix!==At&&(this._prevVals={})}set hass(t){this._hass=t;const e=t?.language,i="function"==typeof semLocalize;let s=!1;if((e!==this._lang||i&&!this._localizeReady)&&(this._lang=e,this._localizeReady=i,s=!0),this._isFrozen()&&!s)return;const r=Rt(this._prefix||At);let a=!1;for(const e of r)if(this._prevVals[e]!==t.states[e]?.state){a=!0;break}if(a||s){for(const e of r)this._prevVals[e]=t.states[e]?.state;this._scheduleUpdate()}}get hass(){return this._hass}_val(t,e=0){return this._state(`${this._prefix}${t}`,e)}_valStr(t){return this._stateStr(`${this._prefix}${t}`)}_fmt(t,e=1){return null==t||isNaN(t)?"—":t.toFixed(e)}render(){if(!this._config)return K;const t=this._theme(),e=this._val("solar_power"),i=this._val("daily_solar_energy"),s=this._val("monthly_solar_yield_energy"),r=this._val("yearly_solar_yield_energy"),a=Math.min(Math.max(e/1e4,0),1),o=2*Math.PI*42,n=(o*(1-a)).toFixed(1),l=e>50?"solarPulse 3s ease-in-out infinite":"none",c=this._val("flow_solar_to_home_power"),d=this._val("flow_solar_to_home_energy"),p=this._val("flow_solar_to_battery_power"),h=this._val("flow_solar_to_battery_energy"),_=this._val("flow_solar_to_ev_power"),g=this._val("flow_solar_to_ev_energy"),u=this._val("flow_solar_to_grid_power"),f=this._val("flow_solar_to_grid_energy"),m=this._val("forecast_today_kwh"),v=this._val("forecast_tomorrow_kwh"),y=this._val("forecast_remaining_today_kwh"),x=this._val("forecast_peak_power_today_w"),b=this._valStr("forecast_peak_time_today"),$=this._valStr("best_surplus_window"),w=this._val("pv_daily_specific_yield"),k=this._val("pv_performance_vs_forecast"),S=this._val("pv_estimated_annual_degradation"),C=this._valStr("pv_degradation_trend"),E=0!==k?this._fmt(k,0)+"%":"—",z=k>=0?"#8DC892":"#f06292",M=mt(this._hass,this._prefix);return W`
            <style>
                :host { display: block; }
                .wrap {
                    padding: 16px 20px;
                    position: relative;
                    background: ${ut(t,dt.solar)};
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${t.text});
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
                    font-size: 10px; color: var(--secondary-text-color,${t.textSec});
                    font-variant-numeric: tabular-nums;
                }

                /* ── Section ── */
                .section {
                    margin-top: 12px;
                    padding: 10px 12px;
                    background: var(--secondary-background-color, ${t.surface});
                    border: 1px solid var(--divider-color, ${t.surfaceBorder});
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
                .flow-label { font-size: 12px; color: var(--secondary-text-color,${t.textSec}); flex: 1; }
                .flow-vals { text-align: right; }
                .flow-power {
                    font-size: 13px; font-weight: 600;
                    font-variant-numeric: tabular-nums;
                    color: var(--primary-text-color,${t.text});
                }
                .flow-energy {
                    font-size: 10px; color: var(--secondary-text-color,${t.textSec});
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
                    font-size: 12px; color: var(--secondary-text-color,${t.textSec});
                    font-weight: 500;
                }
                .metric-val {
                    font-size: 13px; font-weight: 600;
                    font-variant-numeric: tabular-nums;
                    color: var(--primary-text-color,${t.text});
                }

                /* ── Monthly / yearly chips ── */
                .chips { display: flex; gap: 8px; margin-top: 10px; }
                .chip {
                    flex: 1; text-align: center; padding: 7px 8px;
                    background: var(--secondary-background-color, ${t.surface});
                    border: 1px solid var(--divider-color, ${t.surfaceBorder});
                    border-radius: 10px;
                }
                .chip-label {
                    font-size: 12px; color: var(--secondary-text-color,${t.textTertiary});
                    font-weight: 500; margin-bottom: 2px;
                }
                .chip-value {
                    font-size: 14px; font-weight: 600; color: #ff9800;
                    font-variant-numeric: tabular-nums;
                }
                /* v1.7.1 / #312: per-PV-string chip strip styles */
                ${vt}
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
                    ${M.length>=2?W`
                        <div class="pv-strings-row">
                            ${M.map(t=>W`
                                <div class="pv-chip"
                                     title="${t.entityId}"
                                     data-entity="${t.entityId}"
                                     @click=${()=>this._fireMoreInfo?.(t.entityId)}>
                                    <span class="pv-chip-label">PV${t.slot.replace(/^pv/,"")}</span>
                                    <span class="pv-chip-value">${(Math.abs(t.watts)/1e3).toFixed(2)} kW</span>
                                </div>
                            `)}
                        </div>
                    `:K}

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
                                <div class="solar-power-value">${ht(e)}</div>
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
                                    <div class="flow-power">${ht(c)}</div>
                                    <div class="flow-energy">${this._fmt(d,2)} kWh</div>
                                </div>
                            </div>
                            <div class="flow-row">
                                <div class="flow-dot" style="background:#f06292"></div>
                                <span class="flow-label">${this._t("battery")}</span>
                                <div class="flow-vals">
                                    <div class="flow-power">${ht(p)}</div>
                                    <div class="flow-energy">${this._fmt(h,2)} kWh</div>
                                </div>
                            </div>
                            <div class="flow-row">
                                <div class="flow-dot" style="background:#8DC892"></div>
                                <span class="flow-label">${this._t("ev")}</span>
                                <div class="flow-vals">
                                    <div class="flow-power">${ht(_)}</div>
                                    <div class="flow-energy">${this._fmt(g,2)} kWh</div>
                                </div>
                            </div>
                            <div class="flow-row">
                                <div class="flow-dot" style="background:#8353d1"></div>
                                <span class="flow-label">${this._t("grid_export")}</span>
                                <div class="flow-vals">
                                    <div class="flow-power">${ht(u)}</div>
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
                    ${M.length>=2?W`
                        <div class="section">
                            <div class="section-title">${this._t("pv_strings_today")||"Per string today"}</div>
                            <div class="flows-grid">
                                ${M.map(t=>W`
                                    <div class="flow-row"
                                         style="cursor:pointer"
                                         @click=${()=>this._fireMoreInfo?.(t.entityId)}>
                                        <div class="flow-dot" style="background:#ff9800"></div>
                                        <span class="flow-label">PV${t.slot.replace(/^pv/,"")}</span>
                                        <div class="flow-vals">
                                            <div class="flow-power">${ht(t.watts)}</div>
                                            <div class="flow-energy">${null!=t.energyKwh?this._fmt(t.energyKwh,2)+" kWh":"—"}</div>
                                        </div>
                                    </div>
                                `)}
                            </div>
                        </div>
                    `:K}

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
                                <span class="metric-val">${this._fmt(v,1)} kWh</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("remaining")}</span>
                                <span class="metric-val">${this._fmt(y,1)} kWh</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("peak_power")}</span>
                                <span class="metric-val">
                                    ${x>0?ht(x):"—"}
                                    <span style="font-size:10px;opacity:0.7;margin-left:4px">${b||"—"}</span>
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
                                <span class="metric-val" style="color:${z}">${E}</span>
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
        `}getCardSize(){return 5}static getStubConfig(){return{entity_prefix:At}}},{type:"sem-solar-card",name:"SEM Solar",description:"Consolidated solar production card with flows, forecast, and performance metrics"});const Ot="sensor.sem_",Bt=["solar_power","daily_solar_energy","monthly_solar_yield_energy","forecast_today_kwh","forecast_tomorrow_kwh","self_consumption_rate","autarky_rate","daily_costs","daily_savings","daily_ev_energy","daily_grid_import_energy"];function Pt(t){return Bt.map(e=>`${t}${e}`)}yt("sem-solar-summary-card",class extends xt{static get watchedEntities(){return Pt(Ot)}setConfig(t){super.setConfig(t),this._prefix=t.entity_prefix||Ot,this._prefix!==Ot&&(this._prevVals={})}set hass(t){this._hass=t;const e=t?.language,i="function"==typeof semLocalize;let s=!1;if((e!==this._lang||i&&!this._localizeReady)&&(this._lang=e,this._localizeReady=i,s=!0),this._isFrozen()&&!s)return;const r=Pt(this._prefix||Ot);let a=!1;for(const e of r)if(this._prevVals[e]!==t.states[e]?.state){a=!0;break}if(a||s){for(const e of r)this._prevVals[e]=t.states[e]?.state;this._scheduleUpdate()}}get hass(){return this._hass}_val(t,e=0){return this._state(`${this._prefix}${t}`,e)}_valStr(t){return this._stateStr(`${this._prefix}${t}`)}_fmt(t,e=1){return null==t||isNaN(t)?"—":t.toFixed(e)}render(){if(!this._config)return K;const t=this._theme(),e=this._val("solar_power"),i=this._val("daily_solar_energy"),s=this._val("monthly_solar_yield_energy"),r=this._val("forecast_today_kwh"),a=this._val("forecast_tomorrow_kwh"),o=this._val("self_consumption_rate"),n=this._val("autarky_rate"),l=this._val("daily_costs"),c=this._val("daily_savings"),d=this._val("daily_ev_energy"),p=this._val("daily_grid_import_energy"),h=gt(this._hass),_=(.15+.6*Math.min(e/1e4,1)).toFixed(3),g=2*Math.PI*42,u=(g*(1-(r>0?Math.min(i/r,1):0))).toFixed(1);return W`
            <style>
                :host { display: block; }
                .wrap {
                    padding: 20px;
                    position: relative;
                    background:
                        radial-gradient(ellipse 70% 60% at 50% 25%, rgba(255,152,0,0.06) 0%, transparent 100%),
                        radial-gradient(circle at 2px 2px, ${t.dotColor} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${t.text});
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
                    font-size: 10px;
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
                    color: var(--secondary-text-color, ${t.textSec});
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
                    background: var(--secondary-background-color, ${t.surface});
                    border: 1px solid var(--divider-color, ${t.surfaceBorder});
                    border-radius: 10px;
                    padding: 10px;
                    text-align: center;
                    transition: border-color 0.3s cubic-bezier(0.4,0,0.2,1);
                }
                .metric:hover {
                    border-color: var(--divider-color, ${t.surfaceHover});
                }
                .metric-label {
                    font-size: 10px;
                    color: var(--secondary-text-color, ${t.textTertiary});
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
                                <div class="power">${ht(e)}</div>
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
        `}getCardSize(){return 4}static getStubConfig(){return{entity_prefix:Ot}}},{type:"sem-solar-summary-card",name:"SEM Solar Summary",description:"Lumina-styled solar overview with glow ring and production metrics"});const Lt="sensor.sem_",Ht=["battery_soc","battery_power","battery_charge_power","battery_discharge_power","battery_status","battery_health_score","battery_cycles_estimated","battery_temperature","battery_session_type","battery_session_energy","battery_session_solar_share","battery_session_duration","battery_session_avg_power","battery_session_cost","battery_session_savings","daily_battery_charge_energy","daily_battery_discharge_energy","daily_battery_savings","flow_solar_to_battery_energy","flow_grid_to_battery_energy","monthly_battery_charge_energy","monthly_battery_discharge_energy"],Ut=["#4db6ac","#FFB74D","#BA68C8","#64B5F6"];yt("sem-battery-card",class extends xt{constructor(){super(),this._batteries=[],this._lastStateCount=0}static get watchedEntities(){return Ht.map(t=>`${Lt}${t}`)}setConfig(t){super.setConfig(t),this._prefix=t.entity_prefix||Lt}set hass(t){this._hass=t;const e=t?.language,i="function"==typeof semLocalize;let s=!1;(e!==this._lang||i&&!this._localizeReady)&&(this._lang=e,this._localizeReady=i,s=!0);const r=Object.keys(t.states).length;if(r!==this._lastStateCount){this._lastStateCount=r;const e=[];for(const i of Object.keys(t.states)){const t=i.match(/^sensor\.sem_battery_(b\d+)_power$/);t&&e.push(t[1])}e.sort(),this._batteries=e}if(this._isFrozen()&&!s)return;const a=t?.states[`${this._prefix}battery_status`]?.state;if(("unavailable"===a||"unknown"===a)&&!s)return;let o=Ht.map(e=>t?.states[`${this._prefix}${e}`]?.state||"").join(",")+"|"+e;this._batteries.length&&(o+="|"+this._batteries.map(e=>[`battery_${e}_power`,`battery_${e}_soc`,`battery_${e}_status`,`battery_${e}_capacity_kwh`].map(e=>t?.states[`${this._prefix}${e}`]?.state||"").join(":")).join("|")),(o!==this._lastBattKey||s)&&(this._lastBattKey=o,this._scheduleUpdate())}get hass(){return this._hass}_val(t,e=0){return this._state(`${this._prefix}${t}`,e)}_valStr(t){return this._stateStr(`${this._prefix}${t}`)}_fmt(t,e=1){return null==t||isNaN(t)?"—":t.toFixed(e)}_fmtDuration(t){if(null==t||isNaN(t))return"—";const e=Math.round(t);if(e<90)return`${e} min`;const i=Math.floor(e/60),s=e-60*i;return 0===s?`${i} h`:`${i} h ${s} min`}_batteryName(t){const e=this._hass?.states[`${this._prefix}battery_${t}_power`];let i=t.toUpperCase();return e?.attributes?.friendly_name&&(i=e.attributes.friendly_name.replace(/^SEM\s+/i,"").replace(/\s+Power$/i,"")),i}_renderMiniSocRing(t,e){const i=null!=t?Math.max(0,Math.min(100,t)):0,s=2*Math.PI*22,r=s*(1-i/100);return W`
            <svg viewBox="0 0 56 56" width="56" height="56"
                 style="display:block;">
                <circle cx="28" cy="28" r="${22}" fill="none"
                        stroke="rgba(255,255,255,0.12)" stroke-width="4" />
                <circle cx="28" cy="28" r="${22}" fill="none"
                        stroke="${e}" stroke-width="4"
                        stroke-linecap="round"
                        stroke-dasharray="${s.toFixed(1)}"
                        stroke-dashoffset="${r.toFixed(1)}"
                        transform="rotate(-90 28 28)" />
                <text x="28" y="32" text-anchor="middle"
                      fill="${e}" font-size="13" font-weight="800"
                      font-family="'Segoe UI','Roboto',sans-serif"
                      style="paint-order:stroke;stroke:rgba(0,0,0,0.45);stroke-width:0.5px;">
                    ${null!=t?Math.round(i)+"%":"—"}
                </text>
            </svg>
        `}_renderBatterySection(t,e){const i=Ut[e%Ut.length],s=this._val(`battery_${t}_power`,0),r=this._val(`battery_${t}_soc`,null),a=this._valStr(`battery_${t}_status`)||"idle",o=this._val(`battery_${t}_capacity_kwh`,0),n=this._batteryName(t),l="charging"===a?"charging":"discharging"===a?"discharging":"idle";return W`
            <div class="battery-section">
                <div class="battery-section-header">
                    <div class="battery-dot" style="background:${i}"></div>
                    <span class="battery-section-name">${n}</span>
                    <span class="battery-section-status"
                          style="color:${"charging"===a?"#f06292":"discharging"===a?"#4db6ac":"#999"}">
                        ${this._t(l)}
                    </span>
                </div>
                <div class="battery-section-body">
                    <div class="battery-section-ring">
                        ${this._renderMiniSocRing(r,i)}
                        <span class="battery-section-soc-label">SOC</span>
                    </div>
                    <div class="battery-section-metrics">
                        <div class="bs-row">
                            <span class="bs-label">${this._t("power")}</span>
                            <span class="bs-val"
                                  style="color:${s>50||s<-50?i:""}">
                                ${ht(s)}
                            </span>
                        </div>
                        ${o>0?W`
                            <div class="bs-row">
                                <span class="bs-label">${this._t("capacity")}</span>
                                <span class="bs-val">${this._fmt(o,1)} kWh</span>
                            </div>
                        `:K}
                    </div>
                </div>
            </div>
        `}render(){if(!this._hass||!this._config)return K;const t=this._theme(),e=2*Math.PI*42,i=e.toFixed(1),s=this._val("battery_soc",0),r=this._val("battery_power",0),a=this._val("battery_charge_power",0),o=this._val("battery_discharge_power",0),n=this._valStr("battery_status"),l=this._val("battery_health_score",0),c=this._val("battery_cycles_estimated",0),d=this._val("daily_battery_charge_energy",0),p=this._val("daily_battery_discharge_energy",0),h=this._val("daily_battery_savings",0),_=this._val("monthly_battery_charge_energy",0),g=this._val("monthly_battery_discharge_energy",0),u=this._val("flow_solar_to_battery_energy",0),f=gt(this._hass),m=this._hass?.states[`${this._prefix}battery_temperature`],v=m&&"unavailable"!==m.state&&"unknown"!==m.state?parseFloat(m.state):null,y="charging"===n||a>10,x="discharging"===n||o>10,b=y?this._t("charging"):x?this._t("discharging"):this._t("idle"),$=y?"#f06292":"#4db6ac",w=y?"#f06292":x?"#4db6ac":t.textSec||"#888",k=y||x?"0.5":"0.2",S=y||x?"socPulse 2s ease-in-out infinite":"none",C=(e*(1-Math.min(Math.max(s/100,0),1))).toFixed(1),E=d>0?Math.round(u/d*100):0,z=this._valStr("battery_session_type"),M="charge"===z||"discharge"===z,D="charge"===z,F=M?this._val("battery_session_energy",0):0,I=M?this._val("battery_session_duration",0):0,T=M?this._val("battery_session_avg_power",0):0,A=M?this._val("battery_session_solar_share",0):0,N=M?this._val("battery_session_cost",0):0,R=M?this._val("battery_session_savings",0):0,O=D?"#f06292":"#4db6ac";t.dotColor;const B=t.surface||"rgba(255,255,255,0.06)",P=t.surfaceBorder||"rgba(255,255,255,0.05)",L=t.surfaceHover||"rgba(255,255,255,0.12)",H=t.textSec||"#999",U=t.textTertiary||"#888";return W`
            <style>
                :host { display: block; contain: layout style paint; }
                .wrap {
                    padding: 16px 20px;
                    position: relative;
                    background: ${ut(t,dt.battery)};
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${t.text||"#e0e0e0"});
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
                .metric-label { font-size: 12px; color: var(--secondary-text-color, ${H}); font-weight: 500; }
                .metric-val { font-size: 13px; font-weight: 600; font-variant-numeric: tabular-nums; color: #4db6ac; }
                .chips { display: flex; gap: 8px; margin-top: 14px; flex-wrap: wrap; }
                .chip {
                    flex: 1; min-width: 80px;
                    background: var(--secondary-background-color, ${B});
                    border: 1px solid var(--divider-color, ${P});
                    border-radius: 10px; padding: 8px 10px; text-align: center;
                    transition: border-color 0.3s cubic-bezier(0.4,0,0.2,1);
                }
                .chip:hover { border-color: var(--divider-color, ${L}); }
                .chip-label {
                    font-size: 10px; color: var(--secondary-text-color, ${U});
                    font-weight: 500; letter-spacing: 0.3px; margin-bottom: 3px;
                }
                .chip-value { font-size: 13px; font-weight: 600; font-variant-numeric: tabular-nums; }
                .c-charge { color: #f06292; }
                .c-discharge { color: #4db6ac; }
                .c-savings { color: #8DC892; }
                .chip-src { font-size: 9px; color: var(--secondary-text-color, ${U}); margin-top: 1px; }
                .session-section {
                    margin-top: 14px; padding: 10px 12px;
                    background: var(--secondary-background-color, ${B});
                    border: 1px solid var(--divider-color, ${P});
                    border-radius: 10px;
                }
                .sess-header { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
                .sess-title {
                    font-size: 12px; font-weight: 600;
                    text-transform: uppercase; letter-spacing: 0.5px;
                }
                .sess-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 4px; }
                .sess-item-label { font-size: 10px; color: var(--secondary-text-color, ${U}); }
                .sess-item-value {
                    font-size: 12px; font-weight: 600; font-variant-numeric: tabular-nums;
                    color: var(--primary-text-color, ${t.text||"#e0e0e0"});
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
                    background: ${B};
                    border: 1px solid ${P};
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
                    color: var(--primary-text-color, ${t.text||"#e0e0e0"});
                }
                .battery-section-status {
                    font-size: 0.75em; font-weight: 500;
                    text-transform: uppercase; letter-spacing: 0.05em;
                }
                .battery-section-body {
                    display: flex; align-items: center; gap: 12px;
                }
                .battery-section-ring {
                    flex-shrink: 0; width: 56px; text-align: center;
                }
                .battery-section-soc-label {
                    display: block;
                    font-size: 9px; color: ${H};
                    margin-top: 2px;
                    text-transform: uppercase; letter-spacing: 0.05em;
                }
                .battery-section-metrics {
                    flex: 1;
                    display: flex; flex-direction: column; gap: 2px;
                }
                .bs-row {
                    display: flex; justify-content: space-between; align-items: baseline;
                    padding: 1px 0;
                }
                .bs-label {
                    font-size: 10px; color: ${H};
                    font-weight: 500;
                }
                .bs-val {
                    font-size: 11px; font-weight: 600;
                    color: var(--primary-text-color, ${t.text||"#e0e0e0"});
                    font-variant-numeric: tabular-nums;
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
                }
                .month-chip {
                    flex: 1; text-align: center; padding: 6px 8px;
                    background: var(--secondary-background-color, ${B});
                    border: 1px solid var(--divider-color, ${P});
                    border-radius: 8px;
                }
            </style>

            <svg class="glow-svg">
                <defs>
                    <filter id="batt-glow" x="-50%" y="-50%" width="200%" height="200%">
                        <feGaussianBlur stdDeviation="4" result="blur"/>
                        <feFlood flood-color="${$}" flood-opacity="0.25" result="color"/>
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
                                    style="stroke:${$};opacity:${k}"/>
                                <circle class="ring-bg" cx="50" cy="50" r="42"/>
                                <circle class="soc-arc" cx="50" cy="50" r="42"
                                    stroke-dasharray="${i}"
                                    style="stroke-dashoffset:${C};stroke:${$};animation:${S}"/>
                            </svg>
                            <div class="ring-center">
                                <svg class="battery-icon" width="16" height="22" viewBox="0 0 20 30"
                                    fill="none" stroke="#4db6ac" stroke-width="1.8" opacity="0.7">
                                    <rect x="2" y="4" width="16" height="26" rx="3"/>
                                    <rect x="6" y="0" width="8" height="5" rx="2"
                                        fill="#4db6ac" opacity="0.5" stroke="none"/>
                                </svg>
                                <div class="soc-value" style="color:${$}">
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
                                <span class="metric-val">${ht(r)}</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("status")}</span>
                                <span class="metric-val" style="color:${w}">${b}</span>
                            </div>
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
                                        ${null!=v?`${this._fmt(v,1)} °C`:"—"}
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
                            ${this._batteries.map((t,e)=>this._renderBatterySection(t,e))}
                        </div>
                    `:K}

                    <div class="session-section">
                        <div class="sess-header">
                            <ha-icon icon="mdi:battery-sync"
                                style="--mdc-icon-size:14px;color:${M?O:t.textSec}">
                            </ha-icon>
                            <span class="sess-title" style="color:${M?O:t.textSec}">
                                ${this._t("current_session")}
                            </span>
                        </div>
                        ${M?W`
                        <div class="sess-grid">
                            <div>
                                <div class="sess-item-label">${this._t("energy")}</div>
                                <div class="sess-item-value">${this._fmt(F,2)} kWh</div>
                            </div>
                            <div>
                                <div class="sess-item-label">${this._t("duration")}</div>
                                <div class="sess-item-value">${this._fmtDuration(I)}</div>
                            </div>
                            <div>
                                <div class="sess-item-label">${this._t("avg_power")}</div>
                                <div class="sess-item-value">${ht(T)}</div>
                            </div>
                            <div>
                                <div class="sess-item-label">${this._t("source")}</div>
                                <div class="sess-item-value">
                                    ${D?`${this._t("solar")}: ${this._fmt(A,0)}%`:""}
                                </div>
                            </div>
                            <div>
                                <div class="sess-item-label">${this._t("cost")}</div>
                                <div class="sess-item-value">
                                    ${D?`${this._fmt(N,2)} ${f}`:`${this._t("saved")} ${this._fmt(R,2)} ${f}`}
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
                                ${E>0?`${E}% ${this._t("solar")}`:""}
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
        `}getCardSize(){return 3}static getStubConfig(){return{}}},{type:"sem-battery-card",name:"SEM Battery",description:"Lumina-styled battery hero card with SOC arc ring and key metrics"});const Wt="sensor.sem_",jt=["grid_power","grid_import_power","grid_export_power","grid_status","daily_grid_import_energy","daily_grid_export_energy","monthly_grid_import_energy","monthly_grid_export_energy","consecutive_peak_15min","monthly_consecutive_peak","current_vs_peak_percentage","target_peak_limit","peak_margin","peak_trend","load_management_status","loads_currently_shed","available_load_reduction","controllable_devices_count","tariff_current_import_rate","tariff_current_export_rate","tariff_price_level","tariff_today_min_price","tariff_today_max_price","surplus_total_w","surplus_unallocated_w","surplus_active_devices","surplus_total_devices"];yt("sem-grid-card",class extends xt{static get watchedEntities(){return jt.map(t=>`${Wt}${t}`)}setConfig(t){super.setConfig(t),this._prefix=t.entity_prefix||Wt}set hass(t){this._hass=t;const e=t?.language,i="function"==typeof semLocalize;let s=!1;if((e!==this._lang||i&&!this._localizeReady)&&(this._lang=e,this._localizeReady=i,s=!0),this._isFrozen()&&!s)return;const r=jt.map(e=>t?.states[`${this._prefix}${e}`]?.state||"").join(",")+"|"+e;(r!==this._lastGridKey||s)&&(this._lastGridKey=r,this._scheduleUpdate())}get hass(){return this._hass}_val(t,e=0){return this._state(`${this._prefix}${t}`,e)}_valStr(t){return this._stateStr(`${this._prefix}${t}`)}_fmt(t,e=1){return null==t||isNaN(t)?"—":t.toFixed(e)}_peakColor(t){return t>=90?"#f06292":t>=70?"#ff9800":"#8DC892"}_priceLevelColor(t){return"high"===t?"#f06292":"low"===t?"#8DC892":"—"!==t?"#ff9800":"#888"}_metricRow(t,e){return W`
            <div class="metric-row">
                <span class="metric-label">${this._t(t)}</span>
                <span class="metric-val">${e}</span>
            </div>
        `}render(){if(!this._hass||!this._config)return K;const t=this._theme(),e=gt(this._hass),i=this._val("grid_import_power"),s=this._val("grid_export_power"),r=s>i&&s>10,a=i>10,o=r?"mdi:transmission-tower-export":"mdi:transmission-tower-import",n=r?"#8353d1":"#488fc2",l=a||r?"0.45":"0.1",c=this._valStr("grid_status"),d=""!==c&&"—"!==c?this._t(c.toLowerCase()):r?this._t("exporting"):a?this._t("importing"):this._t("idle"),p=r?"#8353d1":a?"#488fc2":"#888",h=this._val("daily_grid_import_energy"),_=this._val("daily_grid_export_energy"),g=h-_,u=g<=0?"#8353d1":"#488fc2",f=this._val("current_vs_peak_percentage"),m=this._val("consecutive_peak_15min"),v=this._val("monthly_consecutive_peak"),y=this._val("target_peak_limit"),x=this._val("peak_margin"),b=this._valStr("peak_trend"),$=this._peakColor(f),w=x>0?"#8DC892":"#f06292",k=(200*Math.min(Math.max(f/100,0),1)).toFixed(1),S=this._valStr("load_management_status"),C=this._val("loads_currently_shed"),E=this._val("available_load_reduction"),z=this._val("controllable_devices_count"),M=this._val("tariff_current_import_rate"),D=this._val("tariff_current_export_rate"),F=this._valStr("tariff_price_level"),I=this._val("tariff_today_min_price"),T=this._val("tariff_today_max_price"),A=this._priceLevelColor(F),N=this._val("surplus_total_w"),R=this._val("surplus_unallocated_w"),O=Math.max(0,N-R),B=this._val("surplus_active_devices"),P=this._val("surplus_total_devices");t.dotColor;const L=t.textSec||"#999",H=t.surface||"rgba(255,255,255,0.06)",U=t.surfaceBorder||"rgba(255,255,255,0.12)";return W`
            <style>
                :host { display: block; }
                .wrap {
                    padding: 16px 20px;
                    position: relative;
                    background: ${ut(t,dt.inverter)};
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${t.text||"#e0e0e0"});
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
                    color: var(--secondary-text-color, ${L}); margin-bottom: 1px;
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
                    background: var(--secondary-background-color, ${H});
                    border: 1px solid var(--divider-color, ${U});
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
                    font-size: 12px; color: var(--secondary-text-color, ${L}); font-weight: 500;
                }
                .metric-val {
                    font-size: 12px; font-weight: 600; font-variant-numeric: tabular-nums;
                    color: var(--primary-text-color, ${t.text||"#e0e0e0"});
                }
                .net-row {
                    margin-top: 4px; padding-top: 4px;
                    border-top: 1px solid var(--divider-color, ${U});
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
                                        ${a?ht(i):"—"}
                                    </span>
                                </div>
                                <div class="hero-pw">
                                    <span class="hero-pw-label">${this._t("export")}</span>
                                    <span class="hero-pw-val export">
                                        ${r?ht(s):"—"}
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
                            <span class="metric-label"><strong>${this._t("net")}</strong></span>
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
                            <span class="metric-val">${ht(m)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("monthly_peak")}</span>
                            <span class="metric-val">${ht(v)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("peak_limit")}</span>
                            <span class="metric-val">${ht(y)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("peak_margin")}</span>
                            <span class="metric-val" style="color:${w}">
                                ${ht(x)}
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
                            <span class="metric-val">${ht(E)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("controllable_devices")}</span>
                            <span class="metric-val">${this._fmt(z,0)}</span>
                        </div>
                    </div>

                    <!-- Tariff -->
                    <div class="section">
                        <div class="section-title" style="color:#488fc2">${this._t("tariff")}</div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("import_rate")}</span>
                            <span class="metric-val c-import">
                                ${0!==M?`${this._fmt(M,4)} ${e}/kWh`:"—"}
                            </span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("export_rate")}</span>
                            <span class="metric-val c-export">
                                ${0!==D?`${this._fmt(D,4)} ${e}/kWh`:"—"}
                            </span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("price_level")}</span>
                            <span class="metric-val" style="color:${A}">
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
                                ${0!==T?this._fmt(T,4):"—"}
                            </span>
                        </div>
                    </div>

                    <!-- Surplus -->
                    <div class="section">
                        <div class="section-title" style="color:#488fc2">${this._t("surplus")}</div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("total_surplus")}</span>
                            <span class="metric-val c-solar">${ht(N)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("allocated")}</span>
                            <span class="metric-val">${ht(O)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("unallocated")}</span>
                            <span class="metric-val c-green">${ht(R)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("active_devices")}</span>
                            <span class="metric-val">
                                ${Math.round(B)} / ${Math.round(P)}
                            </span>
                        </div>
                    </div>
                </div>
            </ha-card>
        `}getCardSize(){return 5}static getStubConfig(){return{entity_prefix:Wt}}},{type:"sem-grid-card",name:"SEM Grid",description:"Consolidated grid card with import/export, peak management, load control, tariff, and surplus"});const Gt="sensor.sem_",Kt=20;function Vt(t){return 36+556*t}function qt(t){if(!t||"string"!=typeof t)return null;const e=t.match(/^(\d{1,2}):(\d{2})$/);if(!e)return null;const i=parseInt(e[1],10),s=parseInt(e[2],10);return i>24||s>59?null:(i+s/60)/24}function Yt(t){if(!Array.isArray(t))return[];const e=[];let i=-1;for(let s=0;s<24;s++)t[s]&&-1===i?i=s:t[s]||-1===i||(e.push({start:i/24,end:s/24}),i=-1);return-1!==i&&e.push({start:i/24,end:1}),e}yt("sem-schedule-card",class extends xt{static get watchedEntities(){return[`${Gt}tariff_current_import_rate`,`${Gt}tariff_price_level`,`${Gt}night_start_time`,`${Gt}night_end_time`,`${Gt}best_surplus_window`,`${Gt}predicted_surplus_window`,`${Gt}ev_power`,`${Gt}charging_state`,`${Gt}surplus_total_w`]}setConfig(t){super.setConfig(t),this._prefix=t.entity_prefix||Gt}set hass(t){this._hass=t;const e=t?.language,i="function"==typeof semLocalize;let s=!1;if((e!==this._lang||i&&!this._localizeReady)&&(this._lang=e,this._localizeReady=i,s=!0),this._isFrozen()&&!s)return;const r=["tariff_current_import_rate","tariff_price_level","night_start_time","night_end_time","best_surplus_window","predicted_surplus_window","ev_power","charging_state"].map(e=>{const i=t?.states[`${this._prefix}${e}`];return(i?.state||"")+JSON.stringify(i?.attributes?.schedule_today||"")+JSON.stringify(i?.attributes?.tariff_schedule_today||"")+JSON.stringify(i?.attributes?.schedule_surplus_hours||"")+JSON.stringify(i?.attributes?.schedule_ev_hours||"")}),a=r.join("|")+"|"+e;(a!==this._lastSchedKey||s)&&(this._lastSchedKey=a,this._scheduleUpdate())}get hass(){return this._hass}_stateObj(t){return this._hass?.states[`${this._prefix}${t}`]||null}_getTariffSchedule(){const t=this._stateObj("tariff_current_import_rate")||this._stateObj("tariff_price_level"),e=t?.attributes?.schedule_today||t?.attributes?.tariff_schedule_today;if(Array.isArray(e)&&e.length>0)return e.map(t=>({start:qt(t.start)??0,end:qt(t.end)??1,level:t.level||("NT"===(t.tariff||t.type||"HT").toUpperCase()?"cheap":"normal"),type:(t.tariff||t.type||"HT").toUpperCase(),avgPrice:t.avg_price}));const i=(new Date).getDay();return 0===i||6===i?[{start:0,end:1,level:"cheap",type:"NT"}]:[{start:0,end:7/24,level:"cheap",type:"NT"},{start:7/24,end:20/24,level:"normal",type:"HT"},{start:20/24,end:1,level:"cheap",type:"NT"}]}_getNightWindow(){const t=qt(this._stateObj("night_start_time")?.state),e=qt(this._stateObj("night_end_time")?.state);return null==t||null==e?null:{start:t,end:e}}_getPredictedSurplusWindow(){for(const t of["predicted_surplus_window","best_surplus_window"]){const e=this._stateObj(t)?.state;if(!e||"unknown"===e||"unavailable"===e)continue;if(e.toLowerCase().startsWith("tomorrow"))continue;const i=e.split(/[-–]/);if(2!==i.length)continue;const s=qt(i[0].trim()),r=qt(i[1].trim());if(null!=s&&null!=r)return{start:s,end:r}}return null}_getSurplusBlocks(){const t=this._hass?.states[`${this._prefix}surplus_total_w`];return Yt(t?.attributes?.schedule_surplus_hours)}_getEvBlocks(){const t=this._hass?.states[`${this._prefix}surplus_total_w`];return Yt(t?.attributes?.schedule_ev_hours)}_getEvPlanWindow(){const t=this._stateObj("charging_state"),e=t?.attributes?.today_plan;if(!Array.isArray(e))return null;const i=new Date;i.setHours(0,0,0,0);const s=i.getTime()+864e5,r=t=>{const e=new Date(t).getTime();return e<i.getTime()||e>=s?null:(e-i.getTime())/864e5};let a,o,n,l;for(const t of e)"ev_charge_start"===t.kind?a=r(t.when):"ev_min_reached"===t.kind?(o=r(t.when),l=t.values?.kwh):"ev_deadline"===t.kind&&(n=r(t.when));const c=o??n;return null==a&&null==c&&null==n?null:{plan:null!=a&&null!=c&&c>a?[{start:a,end:c,kwh:l}]:[],deadlineFrac:n,minReachedFrac:o}}_getSolarIntensity(){const t=this._stateObj("forecast_peak_time_today")?.state||this._stateObj("peak_time_today")?.state,e=parseFloat(this._stateObj("forecast_today_kwh")?.state||this._stateObj("forecast_today")?.state);if(!t||isNaN(e)||e<.5)return null;const i=qt(t.slice(0,5));if(null==i)return null;const s=new Array(24).fill(0);for(let t=0;t<24;t++){const e=t/24-i,r=Math.exp(-e*e/(.26*.13));s[t]=r}const r=Math.max(...s);return s.map(t=>t/r)}_isEvCharging(){const t=parseFloat(this._stateObj("ev_power")?.state);if(!isNaN(t)&&t>10)return!0;const e=this._stateObj("charging_state")?.state;return e&&"charging"===e.toLowerCase()}_getNowBadges(){const t=this._stateObj("tariff_price_level")?.state,e=["cheap","normal","expensive","very_cheap","very_expensive"].includes(t)?t:null,i="active"===this._stateObj("night_charging_status")?.state,s=parseFloat(this._stateObj("solar_power")?.state),r=!isNaN(s)&&s>50?`${(s/1e3).toFixed(1)} kW`:null,a=this._isEvCharging(),o=this._getEvPlanWindow();return{tariff:e,night:i?"now":null,surplus:r,ev:a?"charging":o?.plan?.length?"planned":null}}_buildSvgContent(t){const e=dt,i=t.textSec||"#888",s=t.textTertiary||"#777",r=t.surface||"rgba(255,255,255,0.03)";let a="";for(let t=0;t<=24;t+=2){const e=Vt(t/24);a+=`<text x="${e}" y="12" text-anchor="middle" fill="${i}"\n                font-size="9" font-family="'Segoe UI','Roboto',sans-serif"\n                font-variant-numeric="tabular-nums">${t.toString().padStart(2,"0")}</text>`}[this._t("tariff"),this._t("night"),this._t("surplus"),this._t("ev")].forEach((t,e)=>{a+=`<text x="32" y="${Kt+22*e+9+3.5}" text-anchor="end" fill="${s}"\n                font-size="9" font-family="'Segoe UI','Roboto',sans-serif">${t}</text>`});for(let t=0;t<4;t++){a+=`<rect x="36" y="${Kt+22*t}" width="556" height="18" rx="3" fill="${r}"/>`}const o={cheap:{fill:"#66bb6a",opacity:.62},normal:{fill:e.solar,opacity:.55},expensive:{fill:"#e91e63",opacity:.9}},n={cheap:"cheap",normal:"normal",expensive:"expensive"};for(const t of this._getTariffSchedule()){const e=Vt(t.start),i=Vt(t.end)-e,s=o[t.level]||o.normal,r=null!=t.avgPrice?`${t.level} · avg ${t.avgPrice.toFixed(2)}`:t.level;if(a+=`<rect x="${e}" y="20" width="${i}" height="18"\n                rx="3" fill="${s.fill}" opacity="${s.opacity}">\n                <title>${r}</title></rect>`,i>30){const s=t.level&&n[t.level]?n[t.level]:t.type.toLowerCase();a+=`<text x="${e+i/2}" y="32.5" text-anchor="middle"\n                    fill="rgba(255,255,255,0.92)" font-size="8" font-weight="600"\n                    font-family="'Segoe UI','Roboto',sans-serif">${this._t(s)}</text>`}}const l=this._getNightWindow();if(l){const t=t=>{const e=Math.round(24*t*60);return`${String(Math.floor(e/60)).padStart(2,"0")}:${String(e%60).padStart(2,"0")}`},e=`${this._t("night")} ${t(l.start)}–${t(l.end)}`;if(l.start>l.end){const t=Vt(l.start);a+=`<rect x="${t}" y="42" width="${Vt(1)-t}"\n                    height="18" rx="3" fill="#42a5f5" opacity="0.55"><title>${e}</title></rect>`,a+=`<rect x="${Vt(0)}" y="42"\n                    width="${Vt(l.end)-Vt(0)}" height="18"\n                    rx="3" fill="#42a5f5" opacity="0.55"><title>${e}</title></rect>`}else{const t=Vt(l.start),i=Vt(l.end)-t;a+=`<rect x="${t}" y="42" width="${i}" height="18"\n                    rx="3" fill="#42a5f5" opacity="0.55"><title>${e}</title></rect>`}}const c=this._getSolarIntensity(),d=parseFloat(this._stateObj("forecast_today_kwh")?.state||NaN);if(c){const t=isNaN(d)?this._t("surplus"):`${this._t("surplus")} · forecast ${d.toFixed(1)} kWh`;for(let e=0;e<24;e++){const i=c[e];if(i<.08)continue;const s=Vt(e/24),r=Vt(1/24);a+=`<rect x="${s}" y="64" width="${r}" height="18"\n                    fill="#fdd835" opacity="${(.55*i).toFixed(2)}"><title>${t}</title></rect>`}}const p=this._getPredictedSurplusWindow();if(p){const t=Vt(p.start),e=Math.max(0,Vt(p.end)-t);a+=`<rect x="${t}" y="64" width="${e}" height="18"\n                rx="3" fill="none" stroke="#fdd835" stroke-width="1"\n                stroke-opacity="0.5" stroke-dasharray="2,2"/>`}for(const t of this._getSurplusBlocks()){const e=Vt(t.start),i=Math.max(0,Vt(t.end)-e);a+=`<rect x="${e}" y="64" width="${i}" height="18"\n                rx="3" fill="#fdd835" opacity="0.62"/>`}const h=this._getEvPlanWindow();if(h?.plan?.length)for(const t of h.plan){const i=Vt(t.start),s=Math.max(0,Vt(t.end)-i),r=t.kwh?`${this._t("plan_ev_charge_start")} → ${this._t("plan_ev_min_reached").replace("{kwh}",t.kwh)}`:this._t("plan_ev_charge_start");a+=`<rect x="${i}" y="86" width="${s}" height="18"\n                    rx="3" fill="${e.ev}" opacity="0.30"\n                    stroke="${e.ev}" stroke-width="0.6" stroke-opacity="0.6"\n                    stroke-dasharray="3,2"><title>${r}</title></rect>`}for(const t of this._getEvBlocks()){const i=Vt(t.start),s=Math.max(0,Vt(t.end)-i);a+=`<rect x="${i}" y="86" width="${s}" height="18"\n                rx="3" fill="${e.ev}" opacity="0.55"/>`}if(null!=h?.deadlineFrac){const t=Vt(h.deadlineFrac);a+=`<line x1="${t}" y1="84" x2="${t}" y2="106"\n                stroke="#f06292" stroke-width="1.2" stroke-dasharray="2,1" opacity="0.85">\n                <title>${this._t("plan_ev_deadline")}</title></line>`}if(this._isEvCharging()){const t=new Date,i=(t.getHours()+t.getMinutes()/60)/24,s=.5/24,r=Math.max(0,i-s),o=Math.min(1,i+s),n=Vt(r),l=Vt(o)-n;a+=`<rect x="${n}" y="86" width="${l}" height="18"\n                rx="3" fill="${e.ev}" opacity="0.95"/>`}const _=new Date,g=Vt((_.getHours()+_.getMinutes()/60)/24);return a+=`<line x1="${g}" y1="18" x2="${g}" y2="104"\n            stroke="#ef5350" stroke-width="1.5" stroke-linecap="round" opacity="0.9"/>`,a+=`<polygon points="${g-3},18 ${g+3},18 ${g},22"\n            fill="#ef5350" opacity="0.9"/>`,a}render(){if(!this._hass||!this._config)return K;const t=this._theme(),e=t.dotColor||"rgba(128,128,128,0.04)",i=this._buildSvgContent(t),s=this._getNowBadges(),r={cheap:"#66bb6a",very_cheap:"#66bb6a",normal:"#ff9800",expensive:"#e91e63",very_expensive:"#e91e63",now:"#42a5f5",charging:"#8DC892",planned:"#8DC892"},a=(t,e)=>{if(!e)return K;const i=r[e]||"#888",s=/\d/.test(e)?e:this._t(e);return W`<span class="now-badge"
                style="color:${i};border-color:${i}55;background:${i}22">${s}</span>`};return W`
            <style>
                :host { display: block; }
                .wrap {
                    padding: 12px 14px 8px;
                    position: relative;
                    background:
                        radial-gradient(ellipse 70% 60% at 50% 25%, rgba(150,202,238,0.06) 0%, transparent 100%),
                        radial-gradient(circle at 2px 2px, ${e} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${t.text||"#e0e0e0"});
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
                    font-size: 10.5px; font-weight: 600;
                    text-transform: capitalize;
                }
                .legend {
                    display: flex; gap: 14px; flex-wrap: wrap;
                    margin-top: 6px; padding-top: 6px;
                    border-top: 1px dashed rgba(255,255,255,0.06);
                    font-size: 10px; color: var(--secondary-text-color, #888);
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
                        <span class="item"><i style="background:${dt.solar}"></i>${this._t("normal")}</span>
                        <span class="item"><i style="background:#e91e63"></i>${this._t("expensive")}</span>
                        <span class="item"><i style="background:#42a5f5"></i>${this._t("night")}</span>
                        <span class="item"><i style="background:#fdd835"></i>${this._t("surplus")}</span>
                        <span class="item"><i style="background:${dt.ev}"></i>${this._t("ev")}</span>
                    </div>
                </div>
            </ha-card>
        `}getCardSize(){return 2}static getStubConfig(){return{}}},{type:"sem-schedule-card",name:"SEM Schedule",description:"24-hour timeline showing tariff, night window, surplus window, and EV charging periods"});const Xt=[{id:"autostart",entity:"number.sem_battery_auto_start_soc",icon:"mdi:play-circle",labelKey:"auto_start_soc",helpKey:"zone_help_autostart",color:"#4db6ac"},{id:"buffer",entity:"number.sem_battery_buffer_soc",icon:"mdi:shield-half-full",labelKey:"buffer_soc",helpKey:"zone_help_buffer",color:"#ff9800"},{id:"floor",entity:"number.sem_battery_assist_floor_soc",icon:"mdi:arrow-collapse-down",labelKey:"assist_floor",helpKey:"zone_help_floor",color:"#488fc2"},{id:"priority",entity:"number.sem_battery_priority_soc",icon:"mdi:shield-alert",labelKey:"priority_soc",helpKey:"zone_help_priority",color:"#f44336"}];yt("sem-battery-zones-card",class extends xt{static get watchedEntities(){return Xt.map(t=>t.entity)}static get properties(){return{...super.properties,_showHelp:{state:!0}}}constructor(){super(),this._showHelp=!1}_toggleHelp(){this._showHelp=!this._showHelp}setConfig(t){super.setConfig(t)}_getDecimalsForZone(t){const e=this._hass?.states[t];return(e&&parseFloat(e.attributes.step)||1)<1?1:0}_renderZoneMarkers(t){return Xt.map(e=>{const i=this._state(e.entity);return W`
                <div class="zone-marker" style="left:${i}%">
                    <div class="zone-dot" style="background:${e.color};border-color:${t.isDark?"#1e232d":"#fff"}"></div>
                    <span class="zone-marker-label">${i.toFixed(0)}%</span>
                </div>
            `})}_renderStepper(t,e){const i=this._state(t.entity),s=this._getDecimalsForZone(t.entity),r=this._t(t.labelKey),a=this._showHelp?this._t(t.helpKey):"";return W`
            <div class="stepper-cell">
                <div class="stepper-row">
                    <ha-icon icon="${t.icon}" style="--mdc-icon-size:18px;color:${t.color}"></ha-icon>
                    <span class="stepper-label">${r}</span>
                    <div class="stepper-controls">
                        <button
                            class="stepper-minus"
                            aria-label="Decrease ${r}"
                            @click=${()=>this._stepNumber(t.entity,-1)}
                            @pointerdown=${()=>this._startHold(t.entity,-1)}
                            @pointerup=${()=>this._stopHold(t.entity)}
                            @pointerleave=${()=>this._stopHold(t.entity)}
                        >−</button>
                        <span class="stepper-value">${i.toFixed(s)}%</span>
                        <button
                            class="stepper-plus"
                            aria-label="Increase ${r}"
                            @click=${()=>this._stepNumber(t.entity,1)}
                            @pointerdown=${()=>this._startHold(t.entity,1)}
                            @pointerup=${()=>this._stopHold(t.entity)}
                            @pointerleave=${()=>this._stopHold(t.entity)}
                        >+</button>
                    </div>
                </div>
                ${this._showHelp?W`<div class="zone-help-text" style="border-left-color:${t.color}">${a}</div>`:K}
            </div>
        `}render(){if(!this._config)return K;const t=this._theme(),e=this._state(Xt[0].entity),i=this._state(Xt[1].entity),s=this._state(Xt[3].entity),r=`${this._t("auto_start_soc")} ${e.toFixed(0)}% · Buffer ${i.toFixed(0)}% · ${this._t("priority_soc")} ${s.toFixed(0)}%`;return W`
            <style>
                :host { display: block; contain: layout style paint; }
                .wrap {
                    padding: 16px;
                    background:
                        radial-gradient(ellipse 70% 60% at 50% 25%, rgba(77,182,172,0.06) 0%, transparent 100%),
                        radial-gradient(circle at 2px 2px, ${t.dotColor} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${t.text});
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
                    color: var(--secondary-text-color, ${t.textSec});
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
                    font-size: 9px;
                    font-weight: 600;
                    margin-top: 2px;
                    color: var(--secondary-text-color, ${t.textSec});
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
                    border: 1px solid ${t.surfaceBorder};
                    background: ${t.surface};
                    color: var(--primary-text-color, ${t.text});
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
                    background: ${t.surfaceHover};
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
                    color: var(--secondary-text-color, ${t.textSec});
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
                    color: var(--secondary-text-color, ${t.textSec});
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
                        ${this._renderZoneMarkers(t)}
                    </div>
                </div>
                <div class="stepper-grid">
                    ${Xt.map(e=>this._renderStepper(e,t))}
                </div>
            </div>
        `}getCardSize(){return 4}static getStubConfig(){return{}}},{type:"custom:sem-battery-zones-card",name:"SEM Battery Zones Card",description:"SOC zone configuration for Solar Energy Management",preview:!1});const Zt="sensor.sem_",Jt=["daily_costs","daily_savings","daily_export_revenue","daily_battery_savings","daily_net_cost","monthly_costs","monthly_savings","monthly_export_revenue","monthly_net_cost","monthly_battery_savings","yearly_costs","yearly_savings","yearly_export_revenue","yearly_net_cost","yearly_battery_savings","lifetime_total_savings","roi_percentage","roi_payback_years","roi_annual_savings","daily_co2_avoided","yearly_co2_avoided","lifetime_co2_avoided","yearly_trees_equivalent","lifetime_trees_equivalent"];yt("sem-costs-card",class extends xt{static get watchedEntities(){return Jt.map(t=>`${Zt}${t}`)}setConfig(t){super.setConfig(t),this._prefix=t.entity_prefix||Zt}_val(t,e=0){const i=this._hass?.states[`${this._prefix}${t}`];return i&&"unavailable"!==i.state&&"unknown"!==i.state?parseFloat(i.state)??e:e}_fmt(t,e=2){return null==t||isNaN(t)?"—":t.toFixed(e)}_fmtCurr(t,e,i=2){return null==t||isNaN(t)?"—":t.toFixed(i)+" "+e}_netColor(t){return t<=0?"#8DC892":"#f06292"}_renderPeriodSection(t,e,i,s,r){const a=this._val(`${t}_costs`),o=this._val(`${t}_savings`),n=this._val(`${t}_battery_savings`),l=this._val(`${t}_export_revenue`),c=this._val(`${t}_net_cost`),d=this._netColor(c);return W`
            <div class="section">
                <div class="section-title">${this._t(e)}</div>
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
                    <span class="metric-label"><strong>${this._t("net")}</strong></span>
                    <span class="metric-val" style="color:${d}">${this._fmtCurr(c,s)}</span>
                </div>
            </div>
        `}render(){if(!this._config||!this._hass)return K;const t=gt(this._hass),e=this._theme(),i=this._val("daily_net_cost"),s=i<=0,r=s?"#8DC892":"#f06292",a=(s?"+":"")+this._fmt(Math.abs(i),2)+" "+t,o=s?this._t("net_saving_today"):this._t("net_cost_today"),n=this._val("roi_percentage"),l=n>=0?"#8DC892":"#f06292",c=this._val("roi_payback_years");return W`
            <ha-card>
                <div class="wrap">
                    <!-- Hero -->
                    <div class="hero">
                        <div class="hero-net" style="color:${r}">${a}</div>
                        <div class="hero-label" style="color:${r}">${o}</div>
                    </div>

                    <!-- Today / Monthly / Yearly (3 columns) -->
                    <div class="three-col">
                        ${this._renderPeriodSection("daily","today","d",t,e)}
                        ${this._renderPeriodSection("monthly","monthly","m",t,e)}
                        ${this._renderPeriodSection("yearly","yearly","y",t,e)}
                    </div>

                    <!-- ROI + Environmental (2 columns) -->
                    <div class="two-col">
                        <div class="section">
                            <div class="section-title">${this._t("roi")}</div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("lifetime_savings")}</span>
                                <span class="metric-val c-green">${this._fmtCurr(this._val("lifetime_total_savings"),t,0)}</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("annual_savings")}</span>
                                <span class="metric-val c-green">${this._fmtCurr(this._val("roi_annual_savings"),t,0)}</span>
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
        `}getCardSize(){return 5}static getStubConfig(){return{entity_prefix:"sensor.sem_"}}},{type:"sem-costs-card",name:"SEM Costs",description:"Consolidated financial card with daily/monthly/yearly costs, savings, ROI, and environmental impact"});const Qt="sensor.sem_",te=[{id:"ev_econ",icon:"mdi:car-electric",color:"#8DC892",titleKey:"ev_charging_economics"},{id:"investment",icon:"mdi:bank",color:"#96CAEE",titleKey:"system_investment_cost"},{id:"demand",icon:"mdi:flash-triangle",color:"#ff9800",titleKey:"demand_charge"},{id:"tariff",icon:"mdi:tag-multiple",color:"#488fc2",titleKey:"tariff_rates"}];yt("sem-costs-detail-card",class extends xt{static get watchedEntities(){return[`${Qt}lifetime_ev_energy`,`${Qt}lifetime_ev_cost`,`${Qt}lifetime_ev_solar_share`,"number.sem_system_investment_cost",`${Qt}monthly_consecutive_peak`,`${Qt}power_charge_cost`,"number.sem_demand_charge_rate",`${Qt}tariff_current_import_rate`,`${Qt}tariff_current_export_rate`,`${Qt}tariff_price_level`,"number.sem_electricity_import_rate","number.sem_electricity_export_rate"]}constructor(){super(),this._collapsed={}}setConfig(t){super.setConfig(t),this._prefix=t.entity_prefix||Qt}_val(t,e=0){const i=this._hass?.states[`${this._prefix}${t}`];return i&&"unavailable"!==i.state&&"unknown"!==i.state?parseFloat(i.state)??e:e}_valStr(t){const e=this._hass?.states[`${this._prefix}${t}`];return e&&"unavailable"!==e.state&&"unknown"!==e.state?e.state:""}_numVal(t,e=0){const i=this._frozenEntities[t];if(i)return i.value;const s=this._hass?.states[t];return s&&"unavailable"!==s.state&&"unknown"!==s.state?parseFloat(s.state)??e:e}_entityExists(t){const e=this._hass?.states[t];return!(!e||"unavailable"===e.state||"unknown"===e.state)}_toggleSection(t){this._collapsed={...this._collapsed,[t]:!this._collapsed[t]},this.requestUpdate()}_sectionSubtitle(t,e){if("ev_econ"===t){const t=this._val("lifetime_ev_energy");if(t<=0)return this._t("no_ev_data");const i=this._val("lifetime_ev_cost"),s=this._val("lifetime_ev_solar_share");return`${(t>0?i/t:0).toFixed(2)} ${e}/kWh · ${s.toFixed(0)}% solar`}if("investment"===t){const t=this._numVal("number.sem_system_investment_cost");return t>0?`${t.toFixed(0)} ${e}`:""}if("demand"===t){const t=this._val("monthly_consecutive_peak"),i=this._val("power_charge_cost");return`${t.toFixed(1)} kW · ${i.toFixed(2)} ${e}`}if("tariff"===t){const t=this._val("tariff_current_import_rate"),i=this._valStr("tariff_price_level");return i?`${t.toFixed(4)} ${e} · ${this._t(i.toLowerCase())}`:`${t.toFixed(4)} ${e}`}return""}_renderStepper(t,e){const i=this._hass?.states[t],s=this._numVal(t),r=i&&parseFloat(i.attributes.step)||1,a=i?.attributes?.unit_of_measurement||"",o=r<1?2:0,n=s.toFixed(o)+(a?" "+a:"");return W`
            <div class="stepper-row">
                <span class="stepper-label">${this._t(e)}</span>
                <div class="stepper-controls">
                    <button
                        class="stepper-minus"
                        aria-label="Decrease"
                        @click=${()=>this._stepNumber(t,-1)}
                        @pointerdown=${()=>this._startHold(t,-1)}
                        @pointerup=${()=>this._stopHold(t)}
                        @pointerleave=${()=>this._stopHold(t)}
                    >−</button>
                    <span class="stepper-value">${n}</span>
                    <button
                        class="stepper-plus"
                        aria-label="Increase"
                        @click=${()=>this._stepNumber(t,1)}
                        @pointerdown=${()=>this._startHold(t,1)}
                        @pointerup=${()=>this._stopHold(t)}
                        @pointerleave=${()=>this._stopHold(t)}
                    >+</button>
                </div>
            </div>
        `}_renderInfoTile(t,e,i,s){return W`
            <div class="info-tile">
                <ha-icon icon="${t}" style="--mdc-icon-size:18px;color:${e}"></ha-icon>
                <div class="info-tile-content">
                    <span class="info-tile-label">${this._t(i)}</span>
                    <span class="info-tile-value">${s}</span>
                </div>
            </div>
        `}_renderSectionBody(t,e){if("ev_econ"===t){const t=this._val("lifetime_ev_energy");if(!(t>0))return W`<div class="info-empty">${this._t("no_ev_data")}</div>`;const i=this._val("lifetime_ev_cost"),s=this._val("lifetime_ev_solar_share"),r=i/t;return W`
                <div class="info-tiles">
                    ${this._renderInfoTile("mdi:currency-usd","#8DC892","cost_per_kwh",r.toFixed(4)+" "+e+"/kWh")}
                    ${this._renderInfoTile("mdi:solar-power","#ff9800","solar_share",s.toFixed(1)+"%")}
                </div>
            `}if("investment"===t)return W`${this._renderStepper("number.sem_system_investment_cost","system_investment_cost")}`;if("demand"===t){const t=this._val("monthly_consecutive_peak"),i=this._val("power_charge_cost");return W`
                <div class="info-tiles">
                    ${this._renderInfoTile("mdi:chart-bell-curve","#ff9800","monthly_peak",t.toFixed(2)+" kW")}
                    ${this._renderInfoTile("mdi:currency-usd","#f06292","demand_charge",i.toFixed(2)+" "+e)}
                </div>
                ${this._renderStepper("number.sem_demand_charge_rate","demand_charge_rate")}
            `}if("tariff"===t){const t=this._hass?.states["sensor.sem_tariff_current_import_rate"],i=this._hass?.states["sensor.sem_tariff_current_export_rate"],s=this._hass?.states[`${this._prefix}tariff_price_level`],r=t?.state??"—",a=t?.attributes?.unit_of_measurement||e,o=i?.state??"—",n=i?.attributes?.unit_of_measurement||e,l=s?.state??"—",c=this._entityExists("number.sem_electricity_import_rate"),d=this._entityExists("number.sem_electricity_export_rate");return W`
                <div class="info-tiles tariff-info-tiles">
                    ${this._renderInfoTile("mdi:transmission-tower-import","#488fc2","current_import_rate",`${r} ${a}`)}
                    ${this._renderInfoTile("mdi:transmission-tower-export","#8353d1","current_export_rate",`${o} ${n}`)}
                    ${this._renderInfoTile("mdi:signal-cellular-outline","#96CAEE","price_level",l?this._t(l):"—")}
                </div>
                ${c?this._renderStepper("number.sem_electricity_import_rate","current_import_rate"):K}
                ${d?this._renderStepper("number.sem_electricity_export_rate","current_export_rate"):K}
            `}return K}_renderSection(t,e){const i=this._collapsed[t.id],s=this._sectionSubtitle(t.id,e);return W`
            <div class="section">
                <div
                    class="section-header"
                    tabindex="0"
                    role="button"
                    aria-expanded="${!i}"
                    @click=${()=>this._toggleSection(t.id)}
                    @keydown=${e=>{"Enter"!==e.key&&" "!==e.key||(e.preventDefault(),this._toggleSection(t.id))}}
                >
                    <ha-icon icon="${t.icon}" style="--mdc-icon-size:20px;color:${t.color}"></ha-icon>
                    <span class="section-title-text">${this._t(t.titleKey)}</span>
                    <span class="section-subtitle">${s}</span>
                    <ha-icon
                        class="chevron"
                        icon="mdi:chevron-down"
                        style="--mdc-icon-size:18px;transform:rotate(${i?"-90deg":"0deg"});transition:transform 0.25s ease"
                    ></ha-icon>
                </div>
                ${i?K:W`
                    <div class="section-body">
                        ${this._renderSectionBody(t.id,e)}
                    </div>
                `}
            </div>
        `}render(){if(!this._config||!this._hass)return K;const t=gt(this._hass);return W`
            <div class="wrap">
                ${te.map(e=>this._renderSection(e,t))}
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
        `}getCardSize(){return 8}static getStubConfig(){return{entity_prefix:"sensor.sem_"}}},{type:"custom:sem-costs-detail-card",name:"SEM Costs Detail Card",description:"Financial details — EV economics, investment, demand charge, and tariff rates",preview:!1});const ee="sensor.sem_";yt("sem-charger-status-card",class extends xt{constructor(){super(),this._chargers=[],this._lastStateCount=0}set hass(t){this._hass,this._hass=t;const e=t?.language,i="function"==typeof semLocalize;let s=!1;if((e!==this._lang||i&&!this._localizeReady)&&(this._lang=e,this._localizeReady=i,s=!0),this._isFrozen()&&!s)return;if(this._chargers?.length>0&&!s){const e=this._config?.entity_prefix||ee,i=t.states[`${e}charger_${this._chargers[0]}_power`]?.state;if("unavailable"===i||"unknown"===i)return}const r=Object.keys(t.states).length;if(r!==this._lastStateCount){this._lastStateCount=r;const e=[];for(const i of Object.keys(t.states)){if(i.includes("_flow_"))continue;const t=i.match(/^sensor\.sem_charger_(.+)_power$/);t&&e.push(t[1])}this._chargers=e}const a=this._config?.entity_prefix||ee,o=this._chargers.map(e=>[`charger_${e}_power`,`charger_${e}_session_energy`,`charger_${e}_session_solar_share`,`charger_${e}_taper_trend`].map(e=>t.states[`${a}${e}`]?.state||"").join(":")).join("|");(o!==this._lastKey||s)&&(this._lastKey=o,this._scheduleUpdate())}get hass(){return this._hass}setConfig(t){super.setConfig(t),this._prefix=t.entity_prefix||ee}_val(t,e=0){const i=this._hass?.states[`${this._prefix}${t}`];return i&&"unavailable"!==i.state&&"unknown"!==i.state?parseFloat(i.state)??e:e}_valStr(t){const e=this._hass?.states[`${this._prefix}${t}`];return e&&"unavailable"!==e.state&&"unknown"!==e.state?e.state:""}_chargerName(t){const e=this._hass?.states[`${this._prefix}charger_${t}_power`];let i=t.replace(/_/g," ").replace(/\b\w/g,t=>t.toUpperCase());return e?.attributes?.friendly_name&&(i=e.attributes.friendly_name.replace(/^SEM\s+/i,"").replace(/\s+Power$/i,"")),i}_renderChargerTile(t){const e=this._val(`charger_${t}_power`),i=this._val(`charger_${t}_session_energy`),s=this._val(`charger_${t}_session_solar_share`),r=this._valStr(`charger_${t}_taper_trend`)||"stable",a=this._t(r),o=this._chargerName(t),n=e>50,l=n?"#8DC892":"#888",c=n?this._t("charging"):this._t("idle");return W`
            <div class="charger-tile">
                <div class="charger-glow" style="opacity:${n?"0.15":"0"}"></div>
                <div class="charger-header">
                    <ha-icon icon="mdi:ev-station" style="--mdc-icon-size:20px;color:${l}"></ha-icon>
                    <span class="charger-name">${o}</span>
                    <span class="charger-status" style="color:${l}">${c}</span>
                </div>
                <div class="charger-metrics">
                    <div class="metric">
                        <span class="metric-value">${e.toFixed(0)}</span>
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
                    ${this._chargers.map(t=>this._renderChargerTile(t))}
                </div>
            </div>
        `:K}static get styles(){return a`
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
                font-size: 0.75em;
                color: var(--secondary-text-color, #999);
                margin-left: 1px;
            }
            .metric-label {
                display: block;
                font-size: 0.7em;
                color: var(--secondary-text-color, #999);
                margin-top: 2px;
                text-transform: uppercase;
                letter-spacing: 0.03em;
            }
            .taper-rising  { color: #f06292; }
            .taper-falling { color: #8DC892; }
            .taper-stable  { color: var(--secondary-text-color, #999); }
        `}getCardSize(){return Math.max(2,this._chargers.length)}static getStubConfig(){return{}}},{type:"sem-charger-status-card",name:"SEM Charger Status",description:"Multi-charger status display with per-charger tiles"});const ie="sensor.sem_",se=["#8DC892","#64B5F6"];yt("sem-ev-status-card",class extends xt{static get properties(){return{...super.properties,_showHelp:{state:!0}}}constructor(){super(),this._chargers=[],this._lastStateCount=0,this._showHelp=!1}_toggleHelp(){this._showHelp=!this._showHelp}set hass(t){this._hass,this._hass=t;const e=t?.language,i="function"==typeof semLocalize;let s=!1;if((e!==this._lang||i&&!this._localizeReady)&&(this._lang=e,this._localizeReady=i,s=!0),this._isFrozen()&&!s)return;const r=Object.keys(t.states).length;if(r!==this._lastStateCount){this._lastStateCount=r;const e=[];for(const i of Object.keys(t.states)){if(i.includes("_flow_"))continue;const t=i.match(/^sensor\.sem_charger_(.+)_power$/);t&&e.push(t[1])}this._chargers=e}const a=this._config?.entity_prefix||ie;let o=["ev_connected","ev_charging","ev_power","calculated_current","session_energy","session_solar_share","session_cost","daily_ev_energy","energy_ev_solar_percentage","charging_state"].map(e=>{const i="ev_connected"===e||"ev_charging"===e?"binary_sensor.sem_":a;return t.states[`${i}${e}`]?.state||""}).join(",");if(this._chargers.length>=1){o+="|"+this._chargers.map(e=>[`charger_${e}_power`,`charger_${e}_session_energy`,`charger_${e}_session_energy_external`,`charger_${e}_daily_energy`,`charger_${e}_session_solar_share`,`charger_${e}_estimated_soc`,`charger_${e}_vehicle_soc`].map(e=>t.states[`${a}${e}`]?.state||"").join(":")).join("|"),o+="|"+this._chargers.map(e=>t.states[`switch.sem_charger_${e}_night_charging`]?.state||"").join(":"),o+="|"+this._chargers.map(e=>[t.states[`time.sem_charger_${e}_target_time`]?.state||"",t.states[`switch.sem_charger_${e}_tariff_optimized`]?.state||""].join(":")).join("|");const e=t.states[`${a}charging_state`]?.attributes||{};o+="|"+[e.ev_tariff_waiting,e.ev_deadline_reachable,e.ev_next_cheap_window].join(":"),o+="|"+this._chargers.map(e=>t.states[`number.sem_charger_${e}_daily_ev_target`]?.state||"").join(":"),o+="|"+this._chargers.map(e=>[t.states[`select.sem_charger_${e}_ev_target_type`]?.state||"",t.states[`number.sem_charger_${e}_target_soc`]?.state||"",t.states[`number.sem_charger_${e}_daily_ev_target_max`]?.state||"",t.states[`number.sem_charger_${e}_target_soc_max`]?.state||"",t.states[`number.sem_charger_${e}_ev_battery_capacity_kwh`]?.state||"",t.states[`number.sem_charger_${e}_ev_kwh_per_100km`]?.state||""].join(":")).join("|"),o+="|"+(t.states[`${a}ev_remaining_range`]?.state||"")}o+="|"+this._localizeReady+"|"+this._lang,(o!==this._lastKey||s)&&(this._lastKey=o,this._scheduleUpdate())}get hass(){return this._hass}setConfig(t){super.setConfig(t),this._prefix=t.entity_prefix||ie}_binaryState(t){const e=this._hass?.states[`binary_sensor.sem_${t}`];return"on"===e?.state}_val(t,e=0){const i=this._hass?.states[`${this._prefix}${t}`];return i&&"unavailable"!==i.state&&"unknown"!==i.state?parseFloat(i.state)??e:e}_valStr(t){const e=this._hass?.states[`${this._prefix}${t}`];return e?.state||""}_entityVal(t,e=0){const i=this._frozenEntities[t];if(i)return i.value;const s=this._hass?.states[t];return s&&"unavailable"!==s.state&&"unknown"!==s.state?parseFloat(s.state)??e:e}_fmt(t,e=1){return null==t||isNaN(t)?"—":t.toFixed(e)}_chargerName(t){const e=this._hass?.states[`${this._prefix}charger_${t}_power`];let i=t.replace(/_/g," ").replace(/\b\w/g,t=>t.toUpperCase());return e?.attributes?.friendly_name&&(i=e.attributes.friendly_name.replace(/^SEM\s+/i,"").replace(/\s+Power$/i,"")),i}_renderSocGauge(t){const e=null!=t?Math.max(0,Math.min(100,t)):0,i=e>60?"#8DC892":e>30?"#ff9800":"#f06292",s=Math.max(2,e/100*52);return W`
            <svg viewBox="0 0 44 76" width="44" height="76">
                <rect x="14" y="0" width="16" height="5" rx="2" fill="rgba(255,255,255,0.15)"/>
                <rect x="6" y="4" width="32" height="60" rx="4"
                    fill="none" stroke="rgba(255,255,255,0.15)" stroke-width="2"/>
                <rect x="9" y="${52-s+7}" width="26" height="${s}" rx="2"
                    fill="${i}" opacity="0.7"/>
                <text x="22" y="40" text-anchor="middle"
                    fill="white" font-size="14" font-weight="700"
                    font-family="'Segoe UI','Roboto',sans-serif"
                    opacity="0.95">
                    ${null!=t?Math.round(t)+"%":"—"}
                </text>
            </svg>
        `}_renderPlanStrip(){const t=this._hass?.states["sensor.sem_charging_state"],e=t?.attributes?.today_plan||[];if(!Array.isArray(e)||e.length<2)return K;const i=new Set(["ev_charge_start","ev_min_reached","ev_deadline"]);if(!e.some(t=>i.has(t.kind)))return K;const s=Date.now(),r=432e5,a=s+r,o=100,n=t=>Math.max(0,Math.min(o,(t-s)/r*o)),l=e.filter(t=>["now","night_open","ev_charge_start","ev_min_reached","ev_deadline"].includes(t.kind));l.sort((t,e)=>new Date(t.when)-new Date(e.when));const c=!!t?.attributes?.ev_tariff_waiting,d=[];let p=s,h="idle";for(const t of l){const e=new Date(t.when).getTime();e>p&&e<=a&&d.push({s:p,e:e,state:h}),p=e,"night_open"===t.kind?h=c?"wait":"charging":"ev_charge_start"===t.kind?h="charging":("ev_min_reached"===t.kind||"ev_deadline"===t.kind)&&(h="done")}p<a&&d.push({s:p,e:a,state:h});const _=[];for(const t of e){const e=new Date(t.when).getTime();if("expensive_start"===t.kind&&e<a){const i=t.values?.end;if(i){const[t,s]=i.split(":").map(Number),r=new Date(e);r.setHours(t,s,0,0),r.getTime()<e&&r.setDate(r.getDate()+1),_.push({s:e,e:Math.min(r.getTime(),a),kind:"expensive"})}}else if("cheap_start"===t.kind&&e<a){const i=t.values?.end;if(i){const[t,s]=i.split(":").map(Number),r=new Date(e);r.setHours(t,s,0,0),r.getTime()<e&&r.setDate(r.getDate()+1),_.push({s:e,e:Math.min(r.getTime(),a),kind:"cheap"})}}}const g=[];for(let t=0;t<=12;t+=3){const e=s+3600*t*1e3,i=new Date(e).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"});g.push({x:n(e),label:i})}return W`
            <div class="plan-strip" title="${this._t("today_plan_title")} (12h)">
                <svg viewBox="0 0 ${o} 14" preserveAspectRatio="none" class="strip-svg">
                    ${d.map(t=>j`
                        <rect x="${n(t.s)}" y="3" width="${n(t.e)-n(t.s)}"
                              height="6" fill="${(t=>({idle:"#3a4252",wait:"#8353d1",charging:"#8DC892",done:"#4db6ac"}[t]||"#3a4252"))(t.state)}" />
                    `)}
                    ${_.map(t=>j`
                        <rect x="${n(t.s)}" y="0" width="${n(t.e)-n(t.s)}"
                              height="2" fill="${(t=>"cheap"===t?"#8DC892":"#f06292")(t.kind)}"
                              opacity="0.75" />
                    `)}
                    <line x1="0" y1="9" x2="${o}" y2="9"
                          stroke="rgba(255,255,255,0.08)" stroke-width="0.3" />
                </svg>
                <div class="strip-axis">
                    ${g.map(t=>W`
                        <span class="tick" style="left: ${t.x}%">${t.label}</span>
                    `)}
                </div>
                <div class="strip-legend">
                    <span><i style="background:#3a4252"></i>${this._t("plan_strip_idle")}</span>
                    <span><i style="background:#8353d1"></i>${this._t("plan_strip_wait")}</span>
                    <span><i style="background:#8DC892"></i>${this._t("plan_strip_charging")}</span>
                    <span><i style="background:#4db6ac"></i>${this._t("plan_strip_done")}</span>
                </div>
            </div>
        `}_renderRangeSlider(t,e,i){const s=this._hass?.states[t],r=this._hass?.states[e],a=i?"%":" kWh",o=t=>i?String(Math.round(t)):this._fmt(t,t%1==0?0:1);if(!s||!r){const e=this._entityVal(t,i?80:10);return W`<div class="ct-row">
                <span class="ct-label">${this._t("charge_to")}</span>
                <span class="ct-ctl"><span class="ct-val clickable"
                    @click=${()=>this.dispatchEvent(new CustomEvent("hass-more-info",{bubbles:!0,composed:!0,detail:{entityId:t}}))}
                >${o(e)}${a}</span></span></div>`}const n=Math.min(parseFloat(s.attributes.min??0),parseFloat(r.attributes.min??0)),l=Math.max(parseFloat(s.attributes.max??100),parseFloat(r.attributes.max??100)),c=l-n||1;let d=this._entityVal(t,i?80:10),p=this._entityVal(e,100);p<d&&(p=d);const h=(d-n)/c*100,_=(p-n)/c*100,g=p>=l-1e-6,u=parseFloat(this._hass?.states[t]?.attributes?.step)||(l>50?1:5),f=Math.max(u,.02*(l-n)),m=p-d<f-1e-6;return W`
            <div class="range-wrap">
                <div class="range-labels">
                    <span>${this._t("at_least")} <b style="color:#8DC892">${o(d)}${a}</b></span>
                    <span>${this._t("up_to")} <b style="color:#ff9800">${g?this._t("full"):o(p)+a}</b></span>
                </div>
                <div class="range-track">
                    <div class="range-fill" style="left:${h}%;width:${Math.max(0,_-h)}%"></div>
                    <div class="range-handle range-handle-min" style="left:${h}%"
                        @pointerdown=${i=>this._rangeHandleStart(i,"min",t,e,n,l)}></div>
                    <div class="range-handle range-handle-max" style="left:${_}%"
                        @pointerdown=${i=>this._rangeHandleStart(i,"max",t,e,n,l)}></div>
                    ${m?W`
                        <span class="range-split"
                              style="left:${h}%"
                              title="${this._t("separate_handles")}"
                              @click=${i=>{i.stopPropagation();const s=p-f;s>=n?this._setNumber(t,s):this._setNumber(e,Math.min(l,d+f))}}>
                            <ha-icon icon="mdi:arrow-split-vertical"
                                     style="--mdc-icon-size:14px"></ha-icon>
                        </span>
                    `:K}
                </div>
            </div>`}_rangeHandleStart(t,e,i,s,r,a){t.stopPropagation(),t.preventDefault();const o=t.currentTarget.closest(".range-track");if(!o)return;const n="min"===e?i:s,l="min"===e?s:i,c=this._hass?.states[n],d=parseFloat(c?.attributes?.step)||(a>50?1:.5),p=a-r||1,h=t=>{const i=o.getBoundingClientRect();let s=(t-i.left)/(i.width||1);s=Math.max(0,Math.min(1,s));let n=Math.round((r+s*p)/d)*d;const c=this._entityVal(l,"min"===e?a:r);return n="min"===e?Math.min(n,c):Math.max(n,c),Math.max(r,Math.min(a,n))},_=t=>{this._freezeEntity(n,h(t.clientX)),this.requestUpdate()},g=t=>{window.removeEventListener("pointermove",_),window.removeEventListener("pointerup",g),window.removeEventListener("pointercancel",g),this._setNumber(n,h(t.clientX))};window.addEventListener("pointermove",_),window.addEventListener("pointerup",g),window.addEventListener("pointercancel",g)}_renderChargerSection(t,e){const i=se[e%se.length],s=this._val(`charger_${t}_power`,0),r=this._val(`charger_${t}_session_energy_external`,0),a=this._val(`charger_${t}_session_energy`,0),o=r>0?r:a,n=this._val(`charger_${t}_daily_energy`,0),l=this._val(`charger_${t}_session_solar_share`,0),c=this._val(`charger_${t}_vehicle_soc`,null)??this._val("vehicle_soc",null),d=this._val(`charger_${t}_estimated_soc`,null),p=null!=c?c:d,h=this._chargerName(t),_=this._hass?.states[`binary_sensor.sem_charger_${t}_connected`],g="on"===_?.state,u=s>50,f=u?this._t("charging"):g?this._t("connected"):this._t("idle"),m=this._entityVal(`number.sem_charger_${t}_initial_current`,10),v=this._entityVal(`number.sem_charger_${t}_minimum_current`,6),y=this._entityVal(`number.sem_charger_${t}_vehicle_min_current`,v),x=this._entityVal(`number.sem_charger_${t}_ev_battery_capacity_kwh`,40),b=this._entityVal(`number.sem_charger_${t}_ev_kwh_per_100km`,18),$=`select.sem_charger_${t}_charge_mode`,w=this._stateAttrs($),k=this._stateStr($)||"min_plus_solar",S=w.options||["solar_only","min_plus_solar","always_max","off"],C={solar_only:this._t("charge_mode_solar_only"),solar_plus_cheap:this._t("charge_mode_solar_plus_cheap"),min_plus_solar:this._t("charge_mode_min_plus_solar"),always_max:this._t("charge_mode_always_max"),off:this._t("charge_mode_off")},E=Math.round(this._entityVal("number.sem_battery_buffer_soc",70)),z=Math.round(this._entityVal("number.sem_battery_priority_soc",30)),M=t=>(this._t(t)||"").replace(/\{buffer\}/g,E).replace(/\{priority\}/g,z),D=M(`charge_mode_hint_${k}_surplus`),F=M(`charge_mode_hint_${k}_overnight`),I=M(`charge_mode_hint_${k}_battery`),T=`select.sem_charger_${t}_ev_target_type`,A=this._stateStr(T)||"kwh",N=this._stateAttrs(T).options||["kwh"],R="soc"===A,O=R?`number.sem_charger_${t}_target_soc`:`number.sem_charger_${t}_daily_ev_target`,B=R?`number.sem_charger_${t}_target_soc_max`:`number.sem_charger_${t}_daily_ev_target_max`,P=`time.sem_charger_${t}_target_time`,L=this._stateStr(P),H=L?L.slice(0,5):"—",U=this._stateAttrs(`${this._prefix}charging_state`),j=!1===U.ev_deadline_reachable,G=U.ev_next_cheap_window;let V="";if(G)try{const t=new Date(G);isNaN(t)||(V=t.toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"}))}catch(t){}const q="solar_plus_cheap"===k&&V,Y=this._entityVal(O,R?80:10),X=R?Math.max(0,(Y-p)/100*x):Math.max(0,Y-n),Z=b>0?Math.round(X/b*100):null,J=N.length>1?W`<select class="ct-unit" .value=${A}
                    @click=${t=>t.stopPropagation()}
                    @change=${t=>this._selectOption(T,t.target.value)}>
                    ${N.map(t=>W`<option value=${t} ?selected=${t===A}>${"soc"===t?"%":"kWh"}</option>`)}
                </select>`:W`<span class="ct-unit-static">${R?"%":"kWh"}</span>`;return W`
            <div class="charger-section">
                <div class="charger-header">
                    <div class="charger-dot" style="background:${i}"></div>
                    <span class="charger-name">${h}</span>
                    <span class="charger-status" style="color:${u?i:""}">${f}</span>
                </div>

                <div class="charger-body">
                    <div class="charger-soc">
                        ${this._renderSocGauge(p)}
                        <span class="soc-label">SOC</span>
                    </div>

                    <div class="charger-metrics">
                        <div class="cm-row">
                            <span class="cm-label">${this._t("power")}</span>
                            <span class="cm-value" style="color:${u?i:""}">${ht(s)}</span>
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
                        ${null!=Z&&Z>0?W`<span class="ct-range">· +${Z} km</span>`:K}
                        <span class="ct-spacer"></span>
                        ${J}
                    </div>
                    ${this._renderRangeSlider(O,B,R)}
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
                                    @click=${t=>t.stopPropagation()}
                                    @change=${t=>this._selectOption($,t.target.value)}>
                                ${S.map(t=>W`
                                    <option value=${t} ?selected=${t===k}>
                                        ${C[t]||t}
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
                        ${q?W`
                            <div class="ct-hint-row ct-hint-extra">
                                <span class="ct-hint-label">${this._t("ev_next_cheap")}:</span>
                                <span class="ct-hint-text"><b style="color:#8DC892">${V}</b></span>
                            </div>
                        `:K}
                    </div>
                    `:q?W`
                        <div class="ct-cheap-hint">
                            <span class="ct-hint-label">${this._t("ev_next_cheap")}:</span>
                            <b style="color:#8DC892">${V}</b>
                        </div>
                    `:K}
                    <div class="ct-row clickable"
                        @click=${()=>this.dispatchEvent(new CustomEvent("hass-more-info",{bubbles:!0,composed:!0,detail:{entityId:P}}))}>
                        <span class="ct-label">${this._t("ev_charge_by")}</span>
                        <span class="ct-ctl ct-time">
                            <ha-icon icon="mdi:clock-end" style="--mdc-icon-size:13px;color:#5BC8D8"></ha-icon>
                            ${H}
                        </span>
                    </div>
                    ${j?W`
                        <div class="ct-warn">
                            <ha-icon icon="mdi:clock-alert" style="--mdc-icon-size:14px;color:#f06292"></ha-icon>
                            <span>${this._t("ev_deadline_unreachable_short")}</span>
                        </div>
                    `:K}
                    ${this._renderPlanStrip()}
                </div>

                <div class="charger-settings ${this._showHelp?"help-mode":""}">
                    <div class="setting-cell">
                        <div
                            class="setting-item clickable"
                            @click=${()=>{const e=new CustomEvent("hass-more-info",{bubbles:!0,composed:!0,detail:{entityId:`number.sem_charger_${t}_initial_current`}});this.dispatchEvent(e)}}
                        >
                            <ha-icon icon="mdi:current-ac" style="--mdc-icon-size:16px;color:#64B5F6"></ha-icon>
                            <span class="setting-value">${this._fmt(m,0)}A</span>
                        </div>
                        ${this._showHelp?W`<div class="setting-help">${this._t("tile_help_start_amps")}</div>`:K}
                    </div>
                    <div class="setting-cell">
                        <div
                            class="setting-item clickable"
                            @click=${()=>{const e=new CustomEvent("hass-more-info",{bubbles:!0,composed:!0,detail:{entityId:`number.sem_charger_${t}_minimum_current`}});this.dispatchEvent(e)}}
                        >
                            <ha-icon icon="mdi:speedometer-slow" style="--mdc-icon-size:16px;color:#ff9800"></ha-icon>
                            <span class="setting-value">${this._fmt(v,0)}A</span>
                        </div>
                        ${this._showHelp?W`<div class="setting-help">${this._t("tile_help_min_amps")}</div>`:K}
                    </div>
                    <div class="setting-cell">
                        <div
                            class="setting-item clickable"
                            @click=${()=>{const e=new CustomEvent("hass-more-info",{bubbles:!0,composed:!0,detail:{entityId:`number.sem_charger_${t}_vehicle_min_current`}});this.dispatchEvent(e)}}
                        >
                            <ha-icon icon="mdi:car-electric" style="--mdc-icon-size:16px;color:#8DC892"></ha-icon>
                            <span class="setting-value">${this._fmt(y,0)}A</span>
                        </div>
                        ${this._showHelp?W`<div class="setting-help">${this._t("tile_help_vehicle_min_amps")}</div>`:K}
                    </div>
                    <div class="setting-cell">
                        <div
                            class="setting-item clickable"
                            @click=${()=>{const e=new CustomEvent("hass-more-info",{bubbles:!0,composed:!0,detail:{entityId:`number.sem_charger_${t}_ev_battery_capacity_kwh`}});this.dispatchEvent(e)}}
                        >
                            <ha-icon icon="mdi:car-battery" style="--mdc-icon-size:16px;color:#8DC892"></ha-icon>
                            <span class="setting-value">${this._fmt(x,0)} kWh</span>
                        </div>
                        ${this._showHelp?W`<div class="setting-help">${this._t("tile_help_capacity")}</div>`:K}
                    </div>
                    <div class="setting-cell">
                        <div
                            class="setting-item clickable"
                            @click=${()=>{const e=new CustomEvent("hass-more-info",{bubbles:!0,composed:!0,detail:{entityId:`number.sem_charger_${t}_ev_kwh_per_100km`}});this.dispatchEvent(e)}}
                        >
                            <ha-icon icon="mdi:map-marker-distance" style="--mdc-icon-size:16px;color:#5BC8D8"></ha-icon>
                            <span class="setting-value">${this._fmt(b,0)} kWh/100km</span>
                        </div>
                        ${this._showHelp?W`<div class="setting-help">${this._t("tile_help_consumption")}</div>`:K}
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
        `}render(){if(!this._config||!this._hass)return K;const t=this._binaryState("ev_connected"),e=this._binaryState("ev_charging"),i=this._val("ev_power",0);this._val("calculated_current",0),this._val("session_energy",0);const s=this._val("energy_ev_solar_percentage",0),r=this._val("session_cost",0),a=this._val("daily_ev_energy",0);this._valStr("charging_state");const o=gt(this._hass),n=e?"wrap state-charging":t?"wrap state-connected":"wrap state-disconnected",l=e?this._t("charging"):t?this._t("connected"):this._t("disconnected"),c=e?"status-value charging":t?"status-value connected":"status-value disconnected";return W`
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
                                <circle class="glow-ring" cx="50" cy="50" r="42" style="opacity:${e?"0.6":t?"0.25":"0.08"}"/>
                                <circle class="ring-bg" cx="50" cy="50" r="42"/>
                                <circle class="ring-fill" cx="50" cy="50" r="39"/>
                                <g class="charger-icon" transform="translate(50,46)">
                                    <rect x="-10" y="-16" width="20" height="26" rx="3"/>
                                    <rect x="-6.5" y="-11" width="13" height="10" rx="2"/>
                                    <path d="M-1.5,-1 L0,4 L1.5,-1"/>
                                    <line x1="0" y1="10" x2="0" y2="15"/>
                                    <circle class="indicator-dot" cx="0" cy="18" r="2" stroke="none"/>
                                </g>
                                <g class="lightning-bolt" transform="translate(50,42)" style="opacity:${e?"1":"0"}">
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
                                ${e?W`
                                    <div class="metric-row power-row">
                                        <span class="metric-label">${this._t("power")}</span>
                                        <span class="metric-value power-value">${ht(i)}</span>
                                    </div>
                                `:K}
                            </div>
                        `:W`
                            <div class="metrics-col">
                                <div class="metric-row">
                                    <span class="metric-label">${this._t("status")}</span>
                                    <span class="${c}">${l}</span>
                                </div>
                                ${e?W`
                                    <div class="metric-row power-row">
                                        <span class="metric-label">${this._t("power")}</span>
                                        <span class="metric-value power-value">${ht(i)}</span>
                                    </div>
                                `:K}
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
                    ${this._chargers.length>1?K:W`
                        <div class="bottom-bar">
                            <div class="chip">
                                <span class="chip-label">${this._t("session_cost")}</span>
                                <span class="cost-chip-value">${this._fmt(r,2)} ${o}</span>
                            </div>
                        </div>
                    `}

                    ${this._chargers.length>=1?W`
                        <div class="charger-sections">
                            ${this._chargers.map((t,e)=>this._renderChargerSection(t,e))}
                        </div>
                    `:K}
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
                padding: 1.5px 0;
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
                font-size: 10px;
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
                font-size: 0.75em; font-weight: 500;
                text-transform: uppercase; letter-spacing: 0.05em;
                color: var(--secondary-text-color, #999);
            }
            .charger-body {
                display: flex; align-items: center; gap: 12px;
            }
            .charger-soc {
                flex-shrink: 0; width: 44px; text-align: center;
            }
            .soc-label {
                display: block;
                font-size: 9px; color: var(--secondary-text-color, #999);
                margin-top: 2px;
                text-transform: uppercase; letter-spacing: 0.05em;
            }
            .charger-metrics {
                flex: 1;
                display: flex; flex-direction: column; gap: 2px;
            }
            .cm-row {
                display: flex; justify-content: space-between; align-items: baseline;
                padding: 1px 0;
            }
            .cm-label { font-size: 10px; color: var(--secondary-text-color, #999); font-weight: 500; }
            .cm-value {
                font-size: 11px; font-weight: 600;
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
                font-size: 10px; color: var(--secondary-text-color, #999);
            }
            .setting-item.clickable { cursor: pointer; }
            .setting-label { font-size: 10px; color: var(--secondary-text-color, #999); }
            .setting-value { font-size: 11px; font-weight: 600; color: var(--primary-text-color, #e0e0e0); }
            .setting-toggle {
                font-size: 10px; font-weight: 700;
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
                font-size: 10px; text-transform: uppercase; letter-spacing: 0.05em;
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
                font-size: 10.5px; line-height: 1.35; color: var(--secondary-text-color, #999);
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
                font-size: 11.5px; color: #f06292; padding: 5px 0 2px;
            }
            /* 12h EV plan strip (#282) */
            .plan-strip {
                margin: 8px 0 2px; padding: 4px 0 2px;
                border-top: 1px dashed rgba(255,255,255,0.06);
            }
            .strip-svg {
                width: 100%; height: 14px; display: block;
            }
            .strip-axis {
                position: relative; height: 12px; margin-top: 2px;
                font-size: 9.5px; color: var(--secondary-text-color, #888);
            }
            .strip-axis .tick {
                position: absolute; transform: translateX(-50%);
                font-variant-numeric: tabular-nums; white-space: nowrap;
            }
            .strip-legend {
                display: flex; gap: 8px; flex-wrap: wrap;
                font-size: 9.5px; color: var(--secondary-text-color, #888);
                margin-top: 4px;
            }
            .strip-legend span {
                display: inline-flex; align-items: center; gap: 3px;
            }
            .strip-legend i {
                width: 8px; height: 8px; border-radius: 2px;
                display: inline-block;
            }
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
        `}getCardSize(){return this._chargers.length>=1?3+2*this._chargers.length:3}static getStubConfig(){return{}}},{type:"sem-ev-status-card",name:"SEM EV Status",description:"Lumina-styled EV charging hero card with per-charger intelligence and settings"});const re=["sensor.sem_solar_power","sensor.sem_battery_soc","sensor.sem_autarky_rate","sensor.sem_ev_power","sensor.sem_energy_optimization_score","sensor.sem_energy_tip","sensor.sem_best_surplus_window","sensor.sem_forecast_remaining_today_kwh","sensor.sem_current_vs_peak_percentage","sensor.sem_consecutive_peak_15min","sensor.sem_target_peak_limit","sensor.sem_daily_co2_avoided","sensor.sem_lifetime_co2_avoided","sensor.sem_forecast_source","switch.sem_observer_mode"];yt("sem-home-status-card",class extends xt{static get watchedEntities(){return re}setConfig(t){super.setConfig(t),this._prefix=t.entity_prefix||"sensor.sem_"}_val(t,e=0){const i=this._hass?.states[`${this._prefix}${t}`];return i&&"unavailable"!==i.state&&"unknown"!==i.state?parseFloat(i.state)??e:e}_valStr(t){const e=this._hass?.states[`${this._prefix}${t}`];return e&&"unavailable"!==e.state&&"unknown"!==e.state?e.state:""}_switchOn(t){const e=this._frozenEntities[t];return e?"on"===e.value:"on"===this._hass?.states[t]?.state}_scoreColor(t){return t>=80?"#8DC892":t>=50?"#ff9800":"#f44336"}_peakColor(t){return t>90?"#f44336":t>70?"#ff9800":"#8DC892"}_peakStatusKey(t){return t>90?"peak_critical":t>70?"peak_warning":"peak_safe"}_renderChip(t,e,i){return W`
            <div class="chip">
                <ha-icon icon="${t}" style="--mdc-icon-size:16px;color:${e}"></ha-icon>
                <span class="chip-val">${i}</span>
            </div>
        `}render(){if(!this._config||!this._hass)return K;const t=this._val("solar_power"),e=this._val("battery_soc"),i=this._val("autarky_rate"),s=this._val("ev_power"),r=this._val("energy_optimization_score"),a=this._scoreColor(r),o=this._valStr("energy_tip"),n=this._valStr("best_surplus_window")||"—",l=this._val("forecast_remaining_today_kwh").toFixed(1),c=this._val("current_vs_peak_percentage"),d=this._peakColor(c),p=this._val("consecutive_peak_15min").toFixed(1),h=this._val("target_peak_limit").toFixed(1);this._switchOn("switch.sem_observer_mode");const _=this._valStr("forecast_source"),g={solcast:"Solcast",forecast_solar:"Forecast.Solar",custom:this._t("custom")||"Custom"},u=_?g[_]||_:"—",f=this._val("daily_co2_avoided").toFixed(2),m=this._val("lifetime_co2_avoided").toFixed(1);return W`
            <div class="wrap">

                <!-- 1. Status Chips -->
                <div class="chips-row">
                    ${this._renderChip("mdi:solar-power","#ff9800",ht(t))}
                    ${this._renderChip("mdi:battery","#4db6ac",`${e.toFixed(0)}%`)}
                    ${this._renderChip("mdi:leaf","#8DC892",`${i.toFixed(0)}%`)}
                    ${this._renderChip("mdi:car-electric","#8DC892",s>0?ht(s):"—")}
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

                <!-- 4. Forecast Info -->
                <div class="section-label">${this._t("quick_controls")}</div>
                <div class="controls-row">
                    <div class="forecast-chip">
                        <ha-icon icon="mdi:weather-partly-cloudy"
                                 style="--mdc-icon-size:16px;color:#96CAEE"></ha-icon>
                        <span class="forecast-label">${this._t("forecast")}</span>
                        <span class="forecast-val">${u}</span>
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
                            <span class="env-chip-val">${f} kg</span>
                            <span class="env-chip-label">${this._t("co2_today")}</span>
                        </div>
                    </div>
                    <div class="env-chip">
                        <ha-icon icon="mdi:tree"
                                 style="--mdc-icon-size:18px;color:#8DC892"></ha-icon>
                        <div class="env-chip-content">
                            <span class="env-chip-val">${m} kg</span>
                            <span class="env-chip-label">${this._t("co2_lifetime")}</span>
                        </div>
                    </div>
                </div>

            </div>
        `}static get styles(){return a`
            :host { display: block; }

            .wrap {
                padding: 16px;
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
                font-size: 10px;
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
                font-size: 10px; font-weight: 600;
                text-transform: uppercase; letter-spacing: 0.4px;
                padding: 2px 7px;
                border-radius: 8px;
                border: 1px solid;
                align-self: flex-start;
            }

            /* ─────────────────── 4. Quick controls ─────────────────── */
            .controls-row {
                display: flex; gap: 12px; align-items: center;
                flex-wrap: wrap;
            }
            .observer-toggle {
                display: flex; align-items: center; gap: 8px;
                flex: 1; min-width: 120px;
            }
            .observer-toggle-label {
                font-size: 13px; font-weight: 500; flex: 1;
            }
            .toggle-track {
                position: relative;
                width: 42px; height: 24px;
                border-radius: 12px;
                background: rgba(255,255,255,0.15);
                cursor: pointer;
                transition: background 0.2s;
                flex-shrink: 0;
            }
            .toggle-track.on { background: var(--primary-color, #42a5f5); }
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

            .forecast-chip {
                display: flex; align-items: center; gap: 6px;
                padding: 4px 10px;
                border-radius: 12px;
                border: 1px solid var(--divider-color, rgba(255,255,255,0.12));
                background: var(--secondary-background-color, rgba(255,255,255,0.06));
                flex-shrink: 0;
            }
            .forecast-label {
                font-size: 11px;
                color: var(--secondary-text-color, #999);
                font-weight: 500;
            }
            .forecast-val { font-size: 12px; font-weight: 600; }

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
                font-size: 10px;
                color: var(--secondary-text-color, #999);
                text-transform: uppercase; letter-spacing: 0.3px;
            }

            @media (max-width: 400px) {
                .env-row { flex-direction: column; }
                .controls-row { flex-direction: column; align-items: flex-start; }
            }
        `}getCardSize(){return 5}static getStubConfig(){return{entity_prefix:"sensor.sem_"}}},{type:"custom:sem-home-status-card",name:"SEM Home Status Card",description:"Consolidated status panel for the SEM Home tab",preview:!1});const ae="sensor.sem_tariff_current_import_rate",oe={negative:{color:"#4db6ac",key:"price_negative"},very_cheap:{color:"#8DC892",key:"very_cheap"},cheap:{color:"#8DC892",key:"cheap"},normal:{color:"#ff9800",key:"normal"},expensive:{color:"#f06292",key:"expensive"},very_expensive:{color:"#e53935",key:"very_expensive"}};yt("sem-price-card",class extends xt{setConfig(t){super.setConfig(t),this._entity=t.entity||ae,this._compact=!!t.compact}set hass(t){this._hass=t;const e=t?.states[this._entity],i=e?.attributes||{},s=[e?.state,i.price_level,i.next_cheap_start,(i.upcoming||[]).length,this._lang].join("|"),r="function"==typeof semLocalize;(s!==this._lastKey||r&&!this._localizeReady)&&(this._lastKey=s,this._lang=t?.language,this._localizeReady=r,this.requestUpdate())}get hass(){return this._hass}_hm(t){if(!t)return null;try{return new Date(t).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"})}catch(t){return null}}_levelInfo(t){return oe[t]||{color:"#9e9e9e",key:"normal"}}render(){if(!this._hass||!this._config)return K;const t=this._hass.states[this._entity];if(!t||"unavailable"===t.state||"unknown"===t.state)return W`<ha-card><div class="wrap empty">${this._t("current_electricity_price")}: —</div></ha-card>`;const e=t.attributes||{};if(!1===e.is_dynamic)return this.style.display="none",K;this.style.display="";const i=parseFloat(t.state),s=e.currency||"",r=this._levelInfo(e.price_level),a=t=>null==t||isNaN(t)?"—":Number(t).toFixed(2),o=Array.isArray(e.upcoming)?e.upcoming:[],n=this._hm(e.next_cheap_start),l=this._hm(e.next_cheap_end);return this._compact?W`
                <ha-card>
                    <div class="chip-row">
                        <span class="chip-title">${this._t("current_electricity_price")}</span>
                        <span class="chip-price" style="color:${r.color}">${a(i)}</span>
                        <span class="chip-unit">${s}/kWh</span>
                        <span class="chip-badge" style="background:${r.color}22;color:${r.color};border-color:${r.color}55">
                            ${this._t(r.key)}
                        </span>
                        ${n?W`<span class="chip-next">${this._t("price_next_cheap")}: <b style="color:#8DC892">${n}</b></span>`:K}
                    </div>
                </ha-card>
            `:W`
            <ha-card>
                <div class="wrap">
                    <div class="head">
                        <span class="title">${this._t("current_electricity_price")}</span>
                        ${e.provider&&"unknown"!==e.provider?W`<span class="prov">${e.provider}</span>`:K}
                    </div>
                    <div class="now">
                        <span class="price" style="color:${r.color}">${a(i)}</span>
                        <span class="unit">${s}/kWh</span>
                        <span class="badge" style="background:${r.color}22;color:${r.color};border-color:${r.color}55">
                            ${this._t(r.key)}
                        </span>
                    </div>
                    <div class="summary">
                        <span>${this._t("today")}: <b>min ${a(e.today_min)}</b> · avg ${a(e.today_avg)} · <b>max ${a(e.today_max)}</b></span>
                        ${n?W`<span class="cheap">${this._t("price_next_cheap")}: <b>${n}${l?"–"+l:""}</b></span>`:K}
                    </div>
                    ${o.length>=2?this._renderStrip(o):K}
                </div>
            </ha-card>
        `}_renderStrip(t){const e=Date.now(),i=t.map(t=>({t:new Date(t.t).getTime(),price:t.price,level:t.level})).filter(t=>!isNaN(t.t)).sort((t,e)=>t.t-e.t).filter(t=>t.t>=e-36e5).slice(0,24);if(i.length<2)return K;const s=i.map(t=>t.price),r=Math.min(...s),a=Math.max(...s)-r||1,o=i.length,n=(320-2*(o-1))/o,l=i.map((t,i)=>{const s=6+52*((t.price-r)/a),o=i*(n+2),l=64-s,c=this._levelInfo(t.level).color,d=t.t<=e&&e<t.t+36e5;return j`<rect x="${o}" y="${l}" width="${n}" height="${s}" rx="1.5"
                fill="${c}" opacity="${d?"1":"0.65"}"
                stroke="${d?"#fff":"none"}" stroke-width="${d?"1":"0"}"/>`}),c=i.map((t,e)=>{if(e%6!=0)return K;const i=e*(n+2)+n/2,s=new Date(t.t).getHours();return j`<text x="${i}" y="${75}" text-anchor="middle"
                fill="var(--secondary-text-color,#999)" font-size="9">${String(s).padStart(2,"0")}</text>`});return W`
            <svg class="strip" viewBox="0 0 ${320} ${78}" width="100%" preserveAspectRatio="none">
                ${l}${c}
            </svg>
        `}getCardSize(){return 2}static getStubConfig(){return{entity:ae}}static get styles(){return a`
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
            .summary { display: flex; flex-wrap: wrap; gap: 4px 14px; font-size: 11.5px;
                       color: var(--secondary-text-color,#aaa); margin-bottom: 8px; }
            .summary b { color: var(--primary-text-color,#e0e0e0); font-variant-numeric: tabular-nums; }
            .summary .cheap b { color: #8DC892; }
            .strip { display: block; overflow: visible; }
            .static-note { font-size: 11.5px; color: var(--secondary-text-color,#999); padding-top: 2px; }
            /* Compact chip (#257, compact: true) — one row, glance-only. */
            .chip-row {
                display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
                padding: 8px 14px;
            }
            .chip-title { font-size: 12px; font-weight: 600; color: var(--primary-text-color,#e0e0e0); }
            .chip-price { font-size: 17px; font-weight: 700; font-variant-numeric: tabular-nums; line-height: 1; }
            .chip-unit { font-size: 12px; color: var(--secondary-text-color,#999); }
            .chip-badge { font-size: 10.5px; font-weight: 600; padding: 1px 8px;
                          border-radius: 9px; border: 1px solid; text-transform: capitalize; }
            .chip-next { margin-left: auto; font-size: 12px; color: var(--secondary-text-color,#aaa); }
            .chip-next b { font-variant-numeric: tabular-nums; }
        `}},{type:"custom:sem-price-card",name:"SEM Price Card",description:"Dynamic electricity price: current price, level, today range, next cheap window, and an hourly price strip (#257)",preview:!1});const ne=[{id:"info",icon:"mdi:information-outline",color:"#96CAEE",titleKey:"system_info",subtitleFn:t=>{const e=t._val("diag_version")||"—",i=t._val("diag_grid_mode")||"—";return`v${e} · ${"combined"===i?t._t("grid_combined"):"split"===i?t._t("grid_split"):i}`}},{id:"health",icon:"mdi:heart-pulse",color:"#8DC892",titleKey:"health_overview",subtitleFn:t=>`${t._valNum("solar_power").toFixed(0)}W solar · SOC ${t._valNum("battery_soc").toFixed(0)}%`},{id:"diag",icon:"mdi:bug-outline",color:"#ff9800",titleKey:"diagnostics",subtitleFn:()=>""}],le=[{key:"solar_power",icon:"mdi:solar-power",color:"#ff9800",suffix:"W"},{key:"grid_power",icon:"mdi:transmission-tower",color:"#488fc2",suffix:"W"},{key:"battery_soc",icon:"mdi:battery",color:"#4db6ac",suffix:"%"},{key:"forecast_today_kwh",icon:"mdi:weather-sunny",color:"#ff9800",suffix:"kWh"},{key:"tariff_current_import_rate",icon:"mdi:tag",color:"#96CAEE",suffix:""}],ce=["sensor.sem_diag_version","sensor.sem_diag_grid_mode","sensor.sem_diag_battery_capacity","sensor.sem_diag_update_interval","sensor.sem_diag_charger_count","sensor.sem_diag_charger_control","sensor.sem_diag_sensors_unavailable","sensor.sem_diag_ed_config","sensor.sem_solar_power","sensor.sem_grid_power","sensor.sem_battery_soc","sensor.sem_ev_power","sensor.sem_forecast_today_kwh","sensor.sem_tariff_current_import_rate","switch.sem_observer_mode","sensor.sem_home_consumption_power","sensor.sem_grid_import_power","sensor.sem_grid_export_power","sensor.sem_autarky_rate","sensor.sem_self_consumption_rate","sensor.sem_battery_power","sensor.sem_night_charging_status","sensor.sem_battery_status","sensor.sem_grid_status","sensor.sem_charging_state"];yt("sem-system-card",class extends xt{static get watchedEntities(){return ce}constructor(){super(),this._collapsed={info:!1,health:!1,diag:!0},this._copyFeedback=""}setConfig(t){super.setConfig(t),this._prefix=t.entity_prefix||"sensor.sem_"}_val(t){const e=this._hass?.states[`${this._prefix}${t}`];return e&&"unavailable"!==e.state&&"unknown"!==e.state?e.state:""}_valNum(t,e=0){const i=this._hass?.states[`${this._prefix}${t}`];return i&&"unavailable"!==i.state&&"unknown"!==i.state?parseFloat(i.state)??e:e}_switchOn(t){return"on"===this._hass?.states[`switch.sem_${t}`]?.state}_available(t){const e=this._hass?.states[t];return!(!e||"unavailable"===e.state||"unknown"===e.state)}_toggleSection(t){this._collapsed={...this._collapsed,[t]:!this._collapsed[t]},this.requestUpdate()}_copyDiagnostics(){const t=this._val("diag_version")||"—",e=this._val("diag_grid_mode")||"—",i=this._val("diag_charger_count")||"—",s=this._val("diag_charger_control")||"—",r=this._valNum("diag_battery_capacity"),a=`SEM ${t} | Grid: ${e} | Chargers: ${i} (${s}) | Battery: ${r>0?r.toFixed(1):"—"}kWh | Unavailable: ${this._val("diag_sensors_unavailable")||"0"}`,o=this._hass?.states?.["sensor.sem_diag_ed_config"]?.attributes?.energy_dashboard;let n;if(o){const t=t=>t||"—";n=`Solar:   pwr=${t(o.solar?.power)} [${t(o.solar?.power_source)}]  energy=${t(o.solar?.energy)}\nGrid:    pwr=${t(o.grid?.power)} [${t(o.grid?.power_source)}]  imp=${t(o.grid?.import_energy)}  exp=${t(o.grid?.export_energy)}\nBattery: pwr=${t(o.battery?.power)} [${t(o.battery?.power_source)}]  chg=${t(o.battery?.charge_energy)}  dis=${t(o.battery?.discharge_energy)}`}else n=`Config: ${this._val("diag_ed_config")||"—"}`;const l=`${a}\n${n}`;this._writeClipboard(l)}async _writeClipboard(t){const e=t=>{this._copyFeedback=this._t(t),this.requestUpdate(),setTimeout(()=>{this._copyFeedback="",this.requestUpdate()},2e3)};if(navigator?.clipboard?.writeText&&!1!==window.isSecureContext)try{return await navigator.clipboard.writeText(t),void e("copied")}catch(t){console.warn("[SEM System] modern clipboard API failed, falling back to execCommand",t)}try{const i=document.createElement("textarea");i.value=t,i.setAttribute("readonly",""),i.style.position="fixed",i.style.top="0",i.style.left="0",i.style.width="1px",i.style.height="1px",i.style.opacity="0",document.body.appendChild(i),i.focus(),i.select();const s=document.execCommand("copy");document.body.removeChild(i),s?e("copied"):(e("copy_failed"),console.error('[SEM System] execCommand("copy") returned false'))}catch(t){e("copy_failed"),console.error("[SEM System] legacy clipboard fallback threw",t)}}_renderSectionHeader(t,e){const i=this._collapsed[t.id],s=i?"rotate(-90deg)":"rotate(0deg)";return W`
            <div
                class="section-header"
                tabindex="0"
                role="button"
                aria-expanded="${!i}"
                @click=${()=>this._toggleSection(t.id)}
                @keydown=${e=>{"Enter"!==e.key&&" "!==e.key||(e.preventDefault(),this._toggleSection(t.id))}}
            >
                <ha-icon icon="${t.icon}" style="--mdc-icon-size:20px;color:${t.color}"></ha-icon>
                <span class="section-title-text">${this._t(t.titleKey)}</span>
                <span class="section-subtitle">${t.subtitleFn(this)}</span>
                <ha-icon
                    class="chevron"
                    icon="mdi:chevron-down"
                    style="--mdc-icon-size:18px;transform:${s}"
                ></ha-icon>
            </div>
        `}_renderInfoSection(t){const e=this._valNum("diag_battery_capacity"),i=this._valNum("diag_update_interval"),s=this._val("diag_charger_count")||"—",r=this._val("diag_charger_control")||"",a=r?`${s} (${r})`:s;return W`
            <div class="info-row">
                <span class="info-row-label">${this._t("version")}</span>
                <span class="info-row-value">${this._val("diag_version")||"—"}</span>
            </div>
            <div class="info-row">
                <span class="info-row-label">${this._t("grid_mode")}</span>
                <span class="info-row-value">${(()=>{const t=this._val("diag_grid_mode")||"—";return"combined"===t?this._t("grid_combined"):"split"===t?this._t("grid_split"):t})()}</span>
            </div>
            <div class="info-row">
                <span class="info-row-label">${this._t("battery_capacity")}</span>
                <span class="info-row-value">${e>0?e.toFixed(1)+" kWh":"—"}</span>
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
        `}_renderHealthSection(t){return W`
            <div class="health-chips">
                ${le.map(t=>{const e=`${this._prefix}${t.key}`,i=this._available(e),s=this._hass?.states[e],r=s?s.state:"—";let a=t.suffix;if("tariff_current_import_rate"===t.key){const t=s?.attributes?.currency;a=t?` ${t}/kWh`:""}return W`
                        <div class="health-chip" style="background:${i?"rgba(141,200,146,0.12)":"rgba(244,67,54,0.12)"};border:1px solid ${i?"rgba(141,200,146,0.3)":"rgba(244,67,54,0.3)"}">
                            <ha-icon icon="${t.icon}" style="--mdc-icon-size:16px;color:${t.color}"></ha-icon>
                            <span class="chip-value">${i?`${r}${a}`:"—"}</span>
                        </div>
                    `})}
            </div>
        `}_renderToggle(t,e,i){const s="on"===this._hass?.states[t]?.state;return W`
            <div class="toggle-row">
                <span class="toggle-label">${this._t(e)}</span>
                <div
                    class="toggle-track ${s?"on":""}"
                    @click=${()=>this._toggleSwitch(t)}
                >
                    <div class="toggle-thumb"></div>
                </div>
            </div>
        `}_renderDiagBlock(t,e){return W`
            <div class="diag-block">
                <span class="diag-block-label">${this._t(t)}</span>
                <span class="diag-block-text">${e}</span>
            </div>
        `}_renderDiagSection(t){const e=`Solar ${this._valNum("solar_power").toFixed(0)}W · Grid ${this._valNum("grid_power").toFixed(0)}W · Battery ${this._valNum("battery_power").toFixed(0)}W · SOC ${this._valNum("battery_soc").toFixed(0)}% · EV ${this._valNum("ev_power").toFixed(0)}W`,i=`Home ${this._valNum("home_consumption_power").toFixed(0)}W · Import ${this._valNum("grid_import_power").toFixed(0)}W · Export ${this._valNum("grid_export_power").toFixed(0)}W · Autarky ${this._valNum("autarky_rate").toFixed(0)}% · Self ${this._valNum("self_consumption_rate").toFixed(0)}%`,s=this._val("charging_state")||"—",r=this._val("night_charging_status")||"—",a=this._val("battery_status")||"—",o=this._val("grid_status")||"—",n=`${s} · ${this._t("night")}: ${r} · ${this._t("battery")}: ${a} · ${this._t("grid")}: ${o}`;return W`
            ${this._renderDiagBlock("source_sensors",e)}
            ${this._renderDiagBlock("derived_values",i)}
            ${this._renderDiagBlock("mode_status",n)}
        `}_renderSection(t,e,i){const s=this._collapsed[t.id];return W`
            <div class="section">
                ${this._renderSectionHeader(t,i)}
                <div class="section-content ${s?"":"expanded"}">
                    <div class="section-body">
                        ${e(i)}
                    </div>
                </div>
            </div>
        `}render(){if(!this._config)return K;const t=this._theme(),e=!1!==t.isDark,i=t.accent||"#42a5f5",s={info:t=>this._renderInfoSection(t),health:t=>this._renderHealthSection(t),diag:t=>this._renderDiagSection(t)};return W`
            <style>
                :host { display: block; contain: layout style paint; }
                .wrap {
                    padding: 16px;
                    position: relative;
                    background: ${ut(t,dt.inverter)};
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${t.text});
                }

                /* ── Sections ── */
                .section {
                    margin-bottom: 8px;
                    border-radius: 14px;
                    background: ${t.surface};
                    border: 1px solid ${t.surfaceBorder};
                    overflow: hidden;
                    transition: border-color 0.2s;
                }
                .section:hover { border-color: ${e?"rgba(255,255,255,0.18)":"rgba(0,0,0,0.12)"}; }

                .section-header {
                    display: flex; align-items: center; gap: 8px;
                    padding: 12px 14px;
                    cursor: pointer;
                    user-select: none;
                    -webkit-user-select: none;
                    transition: background 0.15s;
                }
                .section-header:hover { background: ${t.surfaceHover}; }
                .section-title-text {
                    font-size: 14px; font-weight: 600;
                    white-space: nowrap;
                }
                .section-subtitle {
                    flex: 1;
                    font-size: 12px;
                    color: var(--secondary-text-color, ${t.textSec});
                    text-align: right;
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    margin-right: 4px;
                }
                .chevron {
                    transition: transform 0.25s ease;
                    color: var(--secondary-text-color, ${t.textSec});
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
                    border-bottom: 1px solid ${t.surfaceBorder};
                }
                .info-row:last-child { border-bottom: none; }
                .info-row-label {
                    font-size: 13px; font-weight: 500;
                    color: var(--secondary-text-color, ${t.textSec});
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
                    border-bottom: 1px solid ${t.surfaceBorder};
                }
                .toggle-row:last-child { border-bottom: none; }
                .toggle-label { font-size: 13px; font-weight: 500; }
                .toggle-track {
                    position: relative;
                    width: 42px; height: 24px;
                    border-radius: 12px;
                    background: ${e?"rgba(255,255,255,0.15)":"rgba(0,0,0,0.18)"};
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
                    border-bottom: 1px solid ${t.surfaceBorder};
                }
                .diag-block:last-child { border-bottom: none; }
                .diag-block-label {
                    display: block;
                    font-size: 11px; font-weight: 600;
                    text-transform: uppercase;
                    letter-spacing: 0.4px;
                    color: var(--secondary-text-color, ${t.textSec});
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
                    border: 1px solid ${t.surfaceBorder};
                    background: ${t.surface};
                    color: var(--primary-text-color, ${t.text});
                    font-size: 13px; font-weight: 600;
                    font-family: inherit;
                    cursor: pointer;
                    transition: background 0.15s, border-color 0.15s;
                }
                .copy-btn:hover { background: ${t.surfaceHover}; border-color: #96CAEE; }
                .copy-btn:active { background: ${e?"rgba(255,255,255,0.15)":"rgba(0,0,0,0.08)"}; }
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
                ${ne.map(e=>this._renderSection(e,s[e.id],t))}
                <div class="copy-row">
                    <button class="copy-btn" @click=${()=>this._copyDiagnostics()}>
                        <ha-icon icon="mdi:content-copy" style="--mdc-icon-size:16px"></ha-icon>
                        ${this._t("copy_diagnostics")}
                    </button>
                    <span class="copy-feedback">${this._copyFeedback}</span>
                </div>
            </div>
        `}getCardSize(){return 8}static getStubConfig(){return{entity_prefix:"sensor.sem_"}}},{type:"custom:sem-system-card",name:"SEM System Card",description:"Consolidated system panel for Solar Energy Management",preview:!1});const de={now:{icon:"mdi:clock-outline",color:"#5BC8D8"},solar_peak:{icon:"mdi:weather-sunny",color:"#ff9800"},solar_end:{icon:"mdi:weather-sunset",color:"#ff9800"},cheap_start:{icon:"mdi:arrow-down-bold",color:"#8DC892"},cheap_end:{icon:"mdi:arrow-up-bold",color:"#ff9800"},expensive_start:{icon:"mdi:flash-alert",color:"#f06292"},expensive_end:{icon:"mdi:flash-off",color:"#8DC892"},night_open:{icon:"mdi:weather-night",color:"#8353d1"},night_end:{icon:"mdi:weather-sunset-up",color:"#ff9800"},ev_charge_start:{icon:"mdi:ev-station",color:"#8DC892"},ev_min_reached:{icon:"mdi:battery-charging-80",color:"#4db6ac"},ev_target_reached:{icon:"mdi:car-electric",color:"#8DC892"},ev_deadline:{icon:"mdi:clock-end",color:"#f06292"},ev_wait:{icon:"mdi:pause-circle",color:"#8353d1"},battery_full:{icon:"mdi:battery-charging-100",color:"#f06292"},battery_empty:{icon:"mdi:battery-low",color:"#4db6ac"}};yt("sem-today-plan-card",class extends xt{setConfig(t){super.setConfig(t),this._entity=t.entity||"sensor.sem_charging_state"}set hass(t){this._hass=t;const e=(t?.states[this._entity]?.attributes||{}).today_plan||[],i=[e.length,e[0]?.when,e.at(-1)?.when,this._lang].join("|"),s="function"==typeof semLocalize;(i!==this._lastKey||s&&!this._localizeReady)&&(this._lastKey=i,this._lang=t?.language,this._localizeReady=s,this.requestUpdate())}get hass(){return this._hass}_hm(t){if(!t)return"—";try{return new Date(t).toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"})}catch(t){return"—"}}_format(t,e){let i=this._t(t);if(!i||i===t)return null;for(const[t,s]of Object.entries(e||{}))i=i.replace(new RegExp(`\\{${t}\\}`,"g"),s);return i}render(){if(!this._hass||!this._config)return K;const t=this._hass.states[this._entity],e=t?.attributes?.today_plan||[];return!Array.isArray(e)||e.length<=1?(this.style.display="none",K):(this.style.display="",W`
            <ha-card>
                <div class="wrap">
                    <div class="head">
                        <ha-icon icon="mdi:calendar-clock" style="--mdc-icon-size:16px;color:#5BC8D8"></ha-icon>
                        <span class="title">${this._t("today_plan_title")}</span>
                    </div>
                    <ul class="rows">
                        ${e.map(t=>{const e=de[t.kind]||de.now,i=this._format(t.label,t.values)||t.label,s=t.detail?this._format(t.detail,t.values):null;return W`
                                <li class="row ${"now"===t.kind?"now":""}">
                                    <span class="time">${this._hm(t.when)}</span>
                                    <ha-icon icon="${e.icon}" style="--mdc-icon-size:14px;color:${e.color}"></ha-icon>
                                    <div class="text">
                                        <span class="label">${i}</span>
                                        ${s?W`<span class="detail">${s}</span>`:K}
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
        `}},{name:"SEM Today's Plan",description:"Forward-looking schedule combining tariff, solar, and EV"});const pe=2;class he{constructor(t){}get _$AU(){return this._$AM._$AU}_$AT(t,e,i){this._$Ct=t,this._$AM=e,this._$Ci=i}_$AS(t,e){return this.update(t,e)}update(t,e){return this.render(...e)}}class _e extends he{constructor(t){if(super(t),this.it=K,t.type!==pe)throw Error(this.constructor.directiveName+"() can only be used in child bindings")}render(t){if(t===K||null==t)return this._t=void 0,this.it=t;if(t===G)return t;if("string"!=typeof t)throw Error(this.constructor.directiveName+"() called with a non-string value");if(t===this.it)return this._t;this.it=t;const e=[t];return e.raw=e,this._t={_$litType$:this.constructor.resultType,strings:e,values:[]}}}_e.directiveName="unsafeHTML",_e.resultType=1;class ge extends _e{}ge.directiveName="unsafeSVG",ge.resultType=2;const ue=(t=>(...e)=>({_$litDirective$:t,values:e}))(ge),fe={solar:{nameKey:"solar",color:"#ff9800"},grid:{nameKey:"grid",color_import:"#488fc2",color_export:"#8353d1"},battery:{nameKey:"battery",color:"#4db6ac"},home:{nameKey:"home",color:"#5BC8D8"},ev:{nameKey:"ev_charger",color:"#8DC892"},inverter:{nameKey:"inverter",color:"#96CAEE"}};yt("sem-flow-card",class extends xt{constructor(){super(),this._lastKey="",this._animFrames={},this._currentValues={},this._compact=!1,this._visible=!0,this._deviceConfigSig="",this._devicePositions=[],this._updateTimer=null,this._resizeObserver=null,this._intersectionObserver=null,this._resizeTimeout=null,this._mode="prefix",this._prefix="sensor.sem_",this._entities=null}setConfig(t){if(this._config=t,t.entity_prefix)this._mode="prefix",this._prefix=t.entity_prefix;else{if(!t.entities)throw new Error('sem-flow-card requires either "entities" or "entity_prefix" config');this._mode="entities",this._entities=t.entities}this._showLabels=!1!==t.show_labels,this._showValues=!1!==t.show_values,this._showGlow=!1!==t.show_glow,this._showInverter=!1!==t.show_inverter,this.requestUpdate()}set hass(t){this._hass,this._hass=t;const e=t?.language;if(e!==this._lang)return this._lang=e,void this.requestUpdate();const i=ft(t,this._prefix);if(i!==this._lastPVKey)return this._lastPVKey=i,void this.requestUpdate();this._visible&&(clearTimeout(this._updateTimer),this._updateTimer=setTimeout(()=>this._updateFlowsImperative(),100))}get hass(){return this._hass}firstUpdated(){this._resizeTimeout=null,this._resizeObserver=new ResizeObserver(t=>{this._resizeTimeout&&clearTimeout(this._resizeTimeout),this._resizeTimeout=setTimeout(()=>{for(const e of t){const t=e.contentRect.width<400;t!==this._compact&&(this._compact=t,this._lastKey="",this._deviceConfigSig="",this.requestUpdate())}},100)}),this._resizeObserver.observe(this),this._intersectionObserver=new IntersectionObserver(t=>{this._visible=t[0].isIntersecting;const e=this.renderRoot.querySelector("svg");e&&(e.style.animationPlayState=this._visible?"running":"paused")},{threshold:.01}),this._intersectionObserver.observe(this)}disconnectedCallback(){super.disconnectedCallback(),this._resizeObserver&&(this._resizeObserver.disconnect(),this._resizeObserver=null),this._intersectionObserver&&(this._intersectionObserver.disconnect(),this._intersectionObserver=null),clearTimeout(this._updateTimer),clearTimeout(this._resizeTimeout);for(const t of Object.keys(this._animFrames))cancelAnimationFrame(this._animFrames[t]);this._animFrames={}}updated(){this._setupClickHandlers(),this._updateFlowsImperative()}static get styles(){return a`
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
        `}render(){if(!this._config)return K;const t=this._getLayout(),e=t.solar,i=t.inverter,s=t.battery,r=t.grid,a=t.home,o=t.ev,n=(2*Math.PI*t.socR).toFixed(1),l=(2*Math.PI*t.autarkyR).toFixed(1),c=t.font.label,d=t.font.value,p=t.font.sub,h=t.font.homeVal,_="'Segoe UI','Roboto',sans-serif",g=this._getNodeColor("grid_import"),u=this._getNodeColor("grid_export"),f=this._getNodeColor("solar"),m=this._getNodeColor("battery"),v=this._getNodeColor("home"),y=this._getNodeColor("ev"),x=fe.inverter.color,b=this._hasNode("solar"),$=this._hasNode("battery"),w=this._hasNode("grid"),k=this._hasNode("ev"),S=this._showInverter&&this._hasNode("inverter"),C=mt(this._hass,this._prefix);return W`
            <ha-card>
                <style>${vt}</style>
                ${C.length>=2?W`
                    <div class="pv-strings-row">
                        ${C.map(t=>W`
                            <div class="pv-chip"
                                 title="${t.entityId}"
                                 data-entity="${t.entityId}"
                                 @click=${()=>this._fireMoreInfo?.(t.entityId)}>
                                <span class="pv-chip-label">PV${t.slot.replace(/^pv/,"")}</span>
                                <span class="pv-chip-value">${(Math.abs(t.watts)/1e3).toFixed(2)} kW</span>
                            </div>
                        `)}
                    </div>
                `:K}
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="${t.vb}" style="background:transparent">
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
                        ${this._svgRaw(this._glowFilter("glowHome",v,10))}
                        ${this._svgRaw(this._glowFilter("glowEV",y,8))}
                        ${this._svgRaw(this._glowFilter("glowInverter",x,6))}
                        <path id="path-solar"   d="${t.paths.solar}"/>
                        <path id="path-home"    d="${t.paths.home}"/>
                        <path id="path-battery" d="${t.paths.battery}"/>
                        <path id="path-grid"    d="${t.paths.grid}"/>
                        <path id="path-ev"      d="${t.paths.ev}"/>
                    </defs>

                    <rect width="100%" height="100%" fill="url(#bgGrad)"/>
                    <rect width="100%" height="90%"  fill="url(#dotGrid)"/>

                    ${this._svgRaw(b?this._track(t.paths.solar,f):"")}
                    ${this._svgRaw(b||S?this._track(t.paths.home,v):"")}
                    ${this._svgRaw($?this._track(t.paths.battery,m):"")}
                    ${this._svgRaw(w?`<path id="track-grid" d="${t.paths.grid}" fill="none" stroke="${g}" stroke-width="1.5" stroke-dasharray="4,6" opacity="0.18"/>`:"")}
                    ${this._svgRaw(k?this._track(t.paths.ev,y):"")}

                    ${this._svgRaw(b?`<g id="flow-solar" class="flow-group" style="opacity:0" data-path-id="path-solar" data-path-d="${t.paths.solar}" data-color="${f}" data-count="2"></g>`:"")}
                    ${this._svgRaw($?`<g id="flow-battery" class="flow-group" style="opacity:0" data-path-id="path-battery" data-path-d="${t.paths.battery}" data-color="${m}" data-count="3"></g>`:"")}
                    ${this._svgRaw(w?`<g id="flow-grid" class="flow-group" style="opacity:0" data-path-id="path-grid" data-path-d="${t.paths.grid}" data-color="${g}" data-count="3"></g>`:"")}
                    ${this._svgRaw(b||S?`<g id="flow-home" class="flow-group" style="opacity:0" data-path-id="path-home" data-path-d="${t.paths.home}" data-color="${v}" data-count="2"></g>`:"")}
                    ${this._svgRaw(k?`<g id="flow-ev" class="flow-group" style="opacity:0" data-path-id="path-ev" data-path-d="${t.paths.ev}" data-color="${y}" data-count="3"></g>`:"")}

                    ${this._svgRaw(b?`\n                    <g id="node-solar" filter="url(#glowSolar)">\n                        ${this._glowRing(e,f)}\n                        <circle cx="${e.cx}" cy="${e.cy}" r="${e.r}" fill="${this._hexToRgba(f,.07)}" stroke="${f}" stroke-width="1.8"/>\n                        <g transform="translate(${e.cx},${e.cy-8})" stroke="${f}" fill="none" opacity="0.75">\n                            <rect x="-16" y="-12" width="32" height="24" rx="3" stroke-width="1.8"/>\n                            <line x1="-16" y1="0" x2="16" y2="0" stroke-width="1.2"/>\n                            <line x1="-5" y1="-12" x2="-5" y2="12" stroke-width="1.2"/>\n                            <line x1="5" y1="-12" x2="5" y2="12" stroke-width="1.2"/>\n                            <line x1="0" y1="12" x2="0" y2="17" stroke-width="1.5"/>\n                            <line x1="-7" y1="17" x2="7" y2="17" stroke-width="1.5"/>\n                        </g>\n                    </g>\n                    <text x="${e.cx}" y="${e.cy+e.r+18}" text-anchor="middle" font-family="${_}" font-size="${c}" font-weight="600" fill="${f}">${this._escSvg(this._getNodeName("solar"))}</text>\n                    <text id="val-solar" x="${e.cx}" y="${e.cy+e.r+18+.9*d}" text-anchor="middle" font-family="${_}" font-size="${d}" font-weight="700" fill="${f}">0 W</text>\n                    <text id="val-today-solar" x="${e.cx}" y="${e.cy+e.r+18+.9*d+p+4}" text-anchor="middle" font-family="${_}" font-size="${p}" fill="${f}" opacity="0.7"> </text>\n                    `:"")}

                    ${this._svgRaw(S?`\n                    <g id="node-inverter" filter="url(#glowInverter)">\n                        <circle cx="${i.cx}" cy="${i.cy}" r="${i.r}" fill="${this._hexToRgba(x,.07)}" stroke="${x}" stroke-width="1"/>\n                        <path d="M${i.cx-10},${i.cy} Q${i.cx-4},${i.cy-8} ${i.cx},${i.cy} Q${i.cx+4},${i.cy+8} ${i.cx+10},${i.cy}" fill="none" stroke="${x}" stroke-width="1.8" opacity="0.7"/>\n                    </g>\n                    <text id="val-inverter-status" x="${i.cx}" y="${i.cy+i.r+14}" text-anchor="middle" font-family="${_}" font-size="${this._compact?11:10}" fill="var(--secondary-text-color,#5a7a9a)" opacity="0.7"> </text>\n                    `:"")}

                    ${this._svgRaw($?`\n                    <g id="node-battery" filter="url(#glowBattery)">\n                        ${this._glowRing(s,m)}\n                        <circle cx="${s.cx}" cy="${s.cy}" r="${s.r}" fill="${this._hexToRgba(m,.07)}" stroke="${m}" stroke-width="1.8"/>\n                        <circle cx="${s.cx}" cy="${s.cy}" r="${t.socR}" fill="none" stroke="${this._hexToRgba(m,.1)}" stroke-width="5"/>\n                        <circle id="soc-arc" cx="${s.cx}" cy="${s.cy}" r="${t.socR}" fill="none" stroke="${m}" stroke-width="5"\n                                stroke-dasharray="${n}" stroke-dashoffset="${n}"\n                                transform="rotate(-90 ${s.cx} ${s.cy})" stroke-linecap="round" opacity="0.75"/>\n                        <g transform="translate(${s.cx},${s.cy}) scale(0.8)" stroke="${m}" fill="none" opacity="0.7">\n                            <rect x="-8" y="-13" width="16" height="26" rx="3" stroke-width="1.8"/>\n                            <rect x="-3" y="-16" width="6" height="4" rx="1.5" fill="${m}" opacity="0.5" stroke="none"/>\n                        </g>\n                    </g>\n                    <text x="${s.cx}" y="${s.cy+s.r+18}" text-anchor="middle" font-family="${_}" font-size="${c}" font-weight="600" fill="${m}">${this._escSvg(this._getNodeName("battery"))}</text>\n                    <text id="val-battery-soc" x="${s.cx}" y="${s.cy+s.r+18+.9*d}" text-anchor="middle" font-family="${_}" font-size="${d}" font-weight="700" fill="${m}">0%</text>\n                    <text id="val-battery-power" x="${s.cx}" y="${s.cy+s.r+18+.9*d+c}" text-anchor="middle" font-family="${_}" font-size="${c}" font-weight="500" fill="${m}" opacity="0.7">0 W</text>\n                    <text id="label-battery-state" x="${s.cx}" y="${s.cy+s.r+18+.9*d+2*c}" text-anchor="middle" font-family="${_}" font-size="${p}" fill="${m}" opacity="0.7"></text>\n                    <text id="val-today-battery" x="${s.cx}" y="${s.cy+s.r+18+.9*d+2*c+p+4}" text-anchor="middle" font-family="${_}" font-size="${p}" fill="${m}" opacity="0.65"> </text>\n                    `:"")}

                    ${this._svgRaw(w?`\n                    <g id="node-grid" filter="url(#glowGridImport)">\n                        ${this._glowRing(r,g)}\n                        <circle id="grid-circle" cx="${r.cx}" cy="${r.cy}" r="${r.r}" fill="${this._hexToRgba(g,.07)}" stroke="${g}" stroke-width="1.8"/>\n                        <g id="grid-icon" transform="translate(${r.cx},${r.cy})" stroke="${g}" fill="none" opacity="0.7" stroke-width="1.8" stroke-linecap="round">\n                            <line x1="0" y1="-16" x2="0" y2="14"/>\n                            <line x1="-10" y1="-8" x2="10" y2="-8"/>\n                            <line x1="-7" y1="-1" x2="7" y2="-1"/>\n                            <line x1="-10" y1="-8" x2="-5" y2="14"/>\n                            <line x1="10" y1="-8" x2="5" y2="14"/>\n                        </g>\n                    </g>\n                    <text x="${r.cx}" y="${r.cy+r.r+18}" text-anchor="middle" font-family="${_}" font-size="${c}" font-weight="600" fill="${g}">${this._escSvg(this._getNodeName("grid"))}</text>\n                    <text id="val-grid" x="${r.cx}" y="${r.cy+r.r+18+.9*d}" text-anchor="middle" font-family="${_}" font-size="${d}" font-weight="700" fill="${g}">0 W</text>\n                    <text id="label-grid" x="${r.cx}" y="${r.cy+r.r+18+.9*d+c}" text-anchor="middle" font-family="${_}" font-size="${p}" font-weight="500" fill="${g}" opacity="0.7">GRID</text>\n                    <text id="val-today-grid" x="${r.cx}" y="${r.cy+r.r+18+.9*d+c+p+4}" text-anchor="middle" font-family="${_}" font-size="${p}" fill="${g}" opacity="0.65"> </text>\n                    `:"")}

                    <g id="node-home" filter="url(#glowHome)">
                        ${this._svgRaw(this._glowRing(a,v,1.4))}
                        <circle cx="${a.cx}" cy="${a.cy}" r="${a.r}" fill="${this._hexToRgba(v,.06)}" stroke="${v}" stroke-width="2"/>
                        <circle cx="${a.cx}" cy="${a.cy}" r="${t.autarkyR}" fill="none" stroke="${this._hexToRgba(v,.08)}" stroke-width="4"/>
                        <circle id="autarky-arc" cx="${a.cx}" cy="${a.cy}" r="${t.autarkyR}" fill="none" stroke="#4CAF50" stroke-width="4"
                                stroke-dasharray="${l}" stroke-dashoffset="${l}"
                                transform="rotate(-90 ${a.cx} ${a.cy})" stroke-linecap="round" opacity="0"/>
                        <g transform="translate(${a.cx},${a.cy-5})" stroke="${v}" fill="none" opacity="0.6" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M-20,2 L0,-14 L20,2"/>
                            <rect x="-14" y="2" width="28" height="20" rx="2"/>
                            <rect x="-4" y="10" width="8" height="12"/>
                        </g>
                    </g>
                    <text x="${a.cx}" y="${a.cy+a.r+18}" text-anchor="middle" font-family="${_}" font-size="${c+1}" font-weight="600" fill="${v}">${this._escSvg(this._getNodeName("home"))}</text>
                    <text id="val-home" x="${a.cx}" y="${a.cy+a.r+18+.9*h}" text-anchor="middle" font-family="${_}" font-size="${h}" font-weight="700" fill="${v}">0 W</text>
                    <text id="val-autarky" x="${a.cx}" y="${a.cy+a.r+18+.9*h+p+4}" text-anchor="middle" font-family="${_}" font-size="${p}" fill="${v}" opacity="0.7">\u00A0</text>
                    <text id="val-today-home" x="${a.cx}" y="${a.cy+a.r+18+.9*h+2*(p+4)}" text-anchor="middle" font-family="${_}" font-size="${p}" fill="${v}" opacity="0.65">\u00A0</text>

                    ${this._svgRaw(k?`\n                    <g id="node-ev" filter="url(#glowEV)">\n                        ${this._glowRing(o,y)}\n                        <circle cx="${o.cx}" cy="${o.cy}" r="${o.r}" fill="${this._hexToRgba(y,.07)}" stroke="${y}" stroke-width="1.8"/>\n                        <g transform="translate(${o.cx},${o.cy})" stroke="${y}" fill="none" opacity="0.7" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">\n                            <rect x="-8" y="-13" width="16" height="22" rx="3"/>\n                            <rect x="-5" y="-9" width="10" height="8" rx="1.5"/>\n                            <path d="M-1,-1 L0,3 L1,-1"/>\n                            <line x1="0" y1="9" x2="0" y2="13"/>\n                            <circle cx="0" cy="15" r="1.5" fill="${y}" opacity="0.4" stroke="none"/>\n                        </g>\n                    </g>\n                    <text x="${o.cx}" y="${o.cy+o.r+18}" text-anchor="middle" font-family="${_}" font-size="${c}" font-weight="600" fill="${y}">${this._escSvg(this._getNodeName("ev"))}</text>\n                    <text id="val-ev" x="${o.cx}" y="${o.cy+o.r+18+.9*d}" text-anchor="middle" font-family="${_}" font-size="${d}" font-weight="700" fill="${y}">0 W</text>\n                    <text id="val-today-ev" x="${o.cx}" y="${o.cy+o.r+18+.9*d+p+4}" text-anchor="middle" font-family="${_}" font-size="${p}" fill="${y}" opacity="0.65"> </text>\n                    <text id="val-ev-subtitle" x="${o.cx}" y="${o.cy+o.r+18+.9*d+2*(p+4)}" text-anchor="middle" font-family="${_}" font-size="${p-1}" fill="${y}" opacity="0.6"></text>\n                    `:"")}

                    <g id="device-labels"></g>

                    <text x="${this._compact?470:960}" y="${this._compact?1050:770}" text-anchor="end"
                          font-family="${_}" font-size="10" font-weight="300" letter-spacing="2"
                          fill="var(--secondary-text-color,#808080)" opacity="0.15">SEM</text>
                </svg>
            </ha-card>
        `}_svgRaw(t){return t?ue(t):K}_escSvg(t){return t?String(t).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;"):""}_updateFlowsImperative(){if(!this._hass)return;let t,e,i,s=this._getState("solar_power");if(this._entities?.solar?.reverse&&(s=-s),"entities"===this._mode&&(this._entities?.battery?.charge||this._entities?.battery?.discharge))t=this._getState("battery_charge_power")-this._getState("battery_discharge_power");else{let e=this._getState("battery_power");t=this._entities?.battery?.reverse?-e:e}if("entities"===this._mode&&this._entities?.grid?.entity){const t=this._getState("grid_power"),s=this._entities.grid.reverse;e=Math.max(0,s?-t:t),i=Math.max(0,s?t:-t)}else e=this._getState("grid_import_power"),i=this._getState("grid_export_power");let r=this._getState("ev_power");this._entities?.ev?.invert&&(r=-r);const a=this._getState("battery_soc"),o=this._getState("autarky_rate"),n=Math.max(0,t),l=Math.max(0,-t),c=this._getEntityId("home_consumption_power");let d;c&&this._hass?.states[c]?(d=this._getState("home_consumption_power"),this._entities?.home?.invert&&(d=-d)):d=Math.max(0,s+e+l-i-n-r);const p=this._getStateStr("daily_solar_energy"),h=this._getStateStr("daily_ev_energy"),_=this._getStateStr("daily_grid_import_energy"),g=this._getStateStr("daily_grid_export_energy"),u=this._getStateStr("daily_battery_energy"),f=this._getStateStr("daily_home_energy"),m={solar:s,battery:t,gridImport:e,gridExport:i,home:d,ev:r,soc:a,autarky:o,dailySolar:p,dailyEv:h,dailyGridImport:_,dailyGridExport:g,dailyBattery:u,dailyHome:f},v=JSON.stringify(m);if(this._lastKey===v)return;this._lastKey=v,this._animateValue("val-solar",s);const y=t>10?"▼ ":t<-10?"▲ ":"";this._animateValue("val-battery-power",Math.abs(t),800,t=>y+ht(t));const x=e>i,b=x?"↓ ":i>10?"↑ ":"";this._animateValue("val-grid",x?e:i,800,t=>b+ht(t)),this._animateValue("val-home",d),this._animateValue("val-ev",r);const $=this._getState("ev_charger_count");this._setText("val-ev-subtitle",$>1?`(${$} ${this._t("chargers")})`:""),this._animateValue("val-battery-soc",a,800,t=>`${t.toFixed(0)}%`);const w=this._getEntityId("autarky_rate");w&&this._animateValue("val-autarky",o,800,t=>`⚡ ${t.toFixed(0)}% self`),this._setText("val-inverter-status",this._getStateStr("charging_state"));const k=this._t("today");this._setText("val-today-solar",p?`${k} ${p} kWh`:""),this._setText("val-today-ev",h?`${k} ${h} kWh`:""),this._setText("val-today-battery",u?`${k} ${u} kWh`:""),this._setText("val-today-home",f?`${k} ${f} kWh`:"");const S=[];if(_&&S.push(`↓${_}`),g&&S.push(`↑${g}`),_&&g){const t=(parseFloat(_)-parseFloat(g)).toFixed(1);S.push(`Net ${t>0?"+":""}${t}`)}this._setText("val-today-grid",S.length?S.join(" ")+" kWh":"");const C=this._getLayout(),E=this.renderRoot.getElementById("soc-arc");if(E){const t=2*Math.PI*C.socR;E.style.strokeDashoffset=(t*(1-a/100)).toFixed(1),E.style.animation=n>10?"socPulse 2s ease-in-out infinite":l>10?"socDrain 2.5s ease-in-out infinite":"none"}const z=this.renderRoot.getElementById("autarky-arc");if(z&&w&&o>0){const t=2*Math.PI*C.autarkyR;z.style.strokeDashoffset=(t*(1-o/100)).toFixed(1),z.style.stroke=this._autarkyColor(o),z.style.opacity="0.75"}else z&&(z.style.opacity="0");const M=x?this._getNodeColor("grid_import"):i>10?this._getNodeColor("grid_export"):this._getNodeColor("grid_import");this._updateGridColor(M,x);const D=this.renderRoot.getElementById("label-grid");D&&(D.textContent=x?this._t("importing"):i>10?this._t("exporting"):this._t("grid"));const F=n>10?"#f06292":l>10?"#4db6ac":this._getNodeColor("battery"),I=this.renderRoot.getElementById("label-battery-state");I&&(I.textContent=n>10?this._t("charging"):l>10?this._t("discharging"):"");for(const t of["val-battery-soc","val-battery-power","label-battery-state","val-today-battery"]){const e=this.renderRoot.getElementById(t);e&&e.setAttribute("fill",F)}const T=this.renderRoot.getElementById("soc-arc");T&&(n>10||l>10)&&(T.style.stroke=F),this._updateFlow("flow-solar",s>10,!1,_t(s)),this._updateFlow("flow-battery",Math.abs(t)>10,t<0,_t(t),F),this._updateFlow("flow-grid",e>10||i>10,x,_t(e||i),M),this._updateFlow("flow-home",d>10,!1,_t(d)),this._updateFlow("flow-ev",r>10,!1,_t(r)),this._setGlowIntensity("node-solar",s,1e4),this._setGlowIntensity("node-battery",Math.abs(t),5e3),this._setGlowIntensity("node-grid",Math.max(e,i),1e4),this._setGlowIntensity("node-home",d,8e3),this._setGlowIntensity("node-ev",r,11e3),this._updateDeviceLabels()}_updateFlow(t,e,i,s,r){const a=this.renderRoot.getElementById(t);if(!a)return;if(a.style.opacity=e?"1":"0",!e)return void(a.dataset.sig="");const o=r||a.dataset.color;r&&(a.dataset.color=r);const n=a.dataset.pathId,l=a.dataset.pathD,c=parseInt(a.dataset.count,10)||2,d=`${i?"r":"f"}:${s.toFixed(1)}:${o}`;a.dataset.sig!==d&&(a.dataset.sig=d,a.innerHTML=this._flowEffects(l,n,o,c,s,i))}_flowEffects(t,e,i,s,r,a){const o=r.toFixed(1),n=a?' keyPoints="1;0" keyTimes="0;1"':"";let l=`<path d="${t}" fill="none" stroke="${i}" stroke-width="3"\n                     stroke-dasharray="12,20" opacity="0.5" stroke-linecap="round">\n                     <animate attributeName="stroke-dashoffset" from="0" to="${a?"32":"-32"}"\n                              dur="${o}s" repeatCount="indefinite"/>\n                   </path>`;for(let t=0;t<s;t++){const a=t/s*r;l+=`\n                <circle r="5" fill="${i}" opacity="0.12">\n                    <animateMotion dur="${o}s" repeatCount="indefinite" calcMode="paced"${n} begin="-${a.toFixed(2)}s">\n                        <mpath href="#${e}"/>\n                    </animateMotion>\n                </circle>\n                <circle r="2.5" fill="${i}" opacity="0.9">\n                    <animateMotion dur="${o}s" repeatCount="indefinite" calcMode="paced"${n} begin="-${a.toFixed(2)}s">\n                        <mpath href="#${e}"/>\n                    </animateMotion>\n                </circle>`}return l}_updateGridColor(t,e){const i=this.renderRoot.getElementById("node-grid");i&&i.setAttribute("filter",`url(#glowGrid${e?"Import":"Export"})`);const s=this.renderRoot.getElementById("grid-circle");s&&(s.setAttribute("stroke",t),s.setAttribute("fill",this._hexToRgba(t,.07)));const r=this.renderRoot.querySelector("#node-grid .glow-ring");r&&r.setAttribute("stroke",t);const a=this.renderRoot.getElementById("grid-icon");a&&a.setAttribute("stroke",t);for(const e of["val-grid","label-grid","val-today-grid"]){const i=this.renderRoot.getElementById(e);i&&i.setAttribute("fill",t)}const o=this.renderRoot.getElementById("track-grid");o&&o.setAttribute("stroke",t)}_updateDeviceLabels(){const t=this.renderRoot.getElementById("device-labels");if(!t)return;const e=this._getDeviceList(),i=e.map(([t,e],i)=>`${e.power_entity}:${e.name}:${e.color||pt[i%pt.length]}:${e.icon_override||""}:${e.daily_energy_entity||""}`).join("|");this._deviceConfigSig!==i&&(this._deviceConfigSig=i,this._buildDeviceDOM(t,e)),this._updateDeviceValues(e)}_getDeviceList(){let t=[];if("entities"===this._mode&&this._entities?.individual)t=this._entities.individual.map((t,e)=>[t.entity||`device_${e}`,{name:t.name||t.entity?.split(".").pop()||`Device ${e+1}`,power_entity:t.entity,device_type:t.device_type||"appliance",is_on:!1,current_power:0,color:t.color,icon_override:t.icon,daily_energy_entity:t.daily_energy}]);else if("prefix"===this._mode){const e=this._hass.states[`${this._prefix}controllable_devices_count`];e?.attributes?.devices&&(t=Object.entries(e.attributes.devices).filter(([,t])=>t.power_entity||t.current_power>0).sort((t,e)=>(t[1].priority||5)-(e[1].priority||5)))}return t.slice(0,6)}_buildDeviceDOM(t,e){if(!e.length)return t.innerHTML="",void(this._devicePositions=[]);const i="'Segoe UI','Roboto',sans-serif",s=this._getLayout(),r=s.home,a=this._compact,o=a?26:24,n=a?2:Math.min(e.length,3),l=a?30:60,c=((a?500:1e3)-2*l)/n,d=s.deviceY,p=a?18:20;let h="";this._devicePositions=[],e.forEach(([t,e],s)=>{let _=e.name||t;_.length>p&&(_=_.substring(0,p-1)+"…");const g=e.color||pt[s%pt.length],u=this._deviceIcon(e.device_type,e.name||t),f=s%n,m=Math.floor(s/n),v=l+f*c+c/2,y=d+m*(a?100:90);this._devicePositions.push({cx:v,cy:y,nodeR:o,color:g}),h+=`<path id="dev-conn-${s}" d="M${r.cx},${r.cy+r.r} C${r.cx},${r.cy+r.r+30} ${v},${y-40} ${v},${y-o}" fill="none" stroke="${g}" stroke-width="1.2" stroke-dasharray="3,5" opacity="0.1"/>`,h+=`<g id="dev-flow-${s}"></g>`,h+=`<path id="dev-path-${s}" d="M${r.cx},${r.cy+r.r} C${r.cx},${r.cy+r.r+30} ${v},${y-40} ${v},${y-o}" fill="none" stroke="none"/>`;const x=e.power_entity?` data-entity="${e.power_entity}"`:"";h+=`<g id="dev-group-${s}" class="device-clickable"${x} data-idx="${s}">`,h+=`<circle id="dev-circle-${s}" cx="${v}" cy="${y}" r="${o}" fill="rgba(128,128,128,0.03)" stroke="${g}" stroke-width="1.2" opacity="0.4"/>`,h+=`<g transform="translate(${v},${y})" stroke="${g}" fill="none" opacity="0.35" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">${u}</g>`,h+=`<text x="${v}" y="${y+o+14}" text-anchor="middle" font-family="${i}" font-size="11" font-weight="500" fill="${g}" opacity="0.8">${this._escSvg(_)}</text>`,h+=`<text id="dev-val-${s}" x="${v}" y="${y+o+14+11+2}" text-anchor="middle" font-family="${i}" font-size="11" font-weight="600" fill="${g}" opacity="0.7">0 W</text>`,h+=`<text id="dev-daily-${s}" x="${v}" y="${y+o+14+26}" text-anchor="middle" font-family="${i}" font-size="11" fill="${g}" opacity="0.65"></text>`,h+="</g>"}),t.innerHTML=h,t.querySelectorAll(".device-clickable[data-entity]").forEach(t=>{const e=parseInt(t.dataset.idx);this._setupNodeActions(t,`device_${e}`,t.dataset.entity)}),e.forEach((t,e)=>{delete this._currentValues[`dev-val-${e}`]})}_updateDeviceValues(t){const e=this._getLayout().home;t.forEach(([t,i],s)=>{const r=i.power_entity?this._hass.states[i.power_entity]:null,a=r?parseFloat(r.state)||0:i.current_power||0,o=a>5,n=i.color||pt[s%pt.length],l=this._devicePositions[s];if(!l)return;if(this._animateValue(`dev-val-${s}`,a),i.daily_energy_entity){const t=this._hass.states[i.daily_energy_entity];this._setText(`dev-daily-${s}`,t?`${this._t("today")} ${t.state} kWh`:"")}const c=this.renderRoot.getElementById(`dev-conn-${s}`);c&&c.setAttribute("opacity",o?"0.3":"0.1");const d=this.renderRoot.getElementById(`dev-circle-${s}`);d&&(d.setAttribute("fill",`rgba(128,128,128,${o?.08:.03})`),d.setAttribute("opacity",o?"1":"0.4"));const p=this.renderRoot.getElementById(`dev-val-${s}`);p&&p.setAttribute("opacity",o?"1":"0.5");const h=this.renderRoot.getElementById(`dev-group-${s}`);if(h){const t=h.querySelector("g[transform]");t&&t.setAttribute("opacity",o?"0.7":"0.35")}const _=this.renderRoot.getElementById(`dev-flow-${s}`);if(_)if(a>5){const t=_t(a).toFixed(1);if(_.dataset.sig!==t){_.dataset.sig=t;const i=`M${e.cx},${e.cy+e.r} C${e.cx},${e.cy+e.r+30} ${l.cx},${l.cy-40} ${l.cx},${l.cy-l.nodeR}`;_.innerHTML=`\n                            <path d="${i}" fill="none" stroke="${n}" stroke-width="2" stroke-dasharray="8,16" opacity="0.4" stroke-linecap="round">\n                                <animate attributeName="stroke-dashoffset" from="0" to="-24" dur="${t}s" repeatCount="indefinite"/>\n                            </path>\n                            <circle r="2" fill="${n}" opacity="0.8">\n                                <animateMotion dur="${t}s" repeatCount="indefinite" calcMode="paced" begin="-${(.3*s).toFixed(1)}s">\n                                    <mpath href="#dev-path-${s}"/>\n                                </animateMotion>\n                            </circle>`}}else""!==_.dataset.sig&&(_.dataset.sig="",_.innerHTML="")})}_setupClickHandlers(){const t={"node-solar":"solar_power","val-solar":"solar_power","val-today-solar":"daily_solar_energy","node-battery":"battery_soc","val-battery-soc":"battery_soc","val-battery-power":"battery_power","label-battery-state":"battery_power","val-today-battery":"daily_battery_energy","node-grid":"grid_import_power","val-grid":"grid_import_power","label-grid":"grid_import_power","val-today-grid":"daily_grid_import_energy","node-home":"home_consumption_power","val-home":"home_consumption_power","val-autarky":"autarky_rate","val-today-home":"daily_home_energy","node-ev":"ev_power","val-ev":"ev_power","val-today-ev":"daily_ev_energy","val-inverter-status":"charging_state"};for(const[e,i]of Object.entries(t)){const t=this._getEntityId(i);if(!t)continue;const s=this.renderRoot.getElementById(e);s&&(s.setAttribute("data-entity",t),s.style.cursor="pointer")}const e=this.renderRoot.querySelector("svg");e&&!e._semClickBound&&(e._semClickBound=!0,e.addEventListener("click",t=>{let i=t.target;for(let t=0;t<5&&i&&i!==e;t++){const t=i.getAttribute?.("data-entity");if(t)return void this._fireMoreInfo(t);i=i.parentElement}}));const i=[{ids:["node-solar"],node:"solar",key:"solar_power"},{ids:["node-battery"],node:"battery",key:"battery_soc"},{ids:["node-grid"],node:"grid",key:"grid_import_power"},{ids:["node-home"],node:"home",key:"home_consumption_power"},{ids:["node-ev"],node:"ev",key:"ev_power"}];for(const{ids:t,node:e,key:s}of i){const i=this._getEntityId(s);if(i)for(const s of t){const t=this.renderRoot.getElementById(s);t&&!t._semActionsBound&&(t._semActionsBound=!0,t.classList.add("clickable-node"),this._setupNodeActions(t,e,i))}}}_setupNodeActions(t,e,i){let s=null,r=!1,a=0,o=null;t.style.cursor="pointer",t.addEventListener("pointerdown",()=>{r=!1,s=setTimeout(()=>{r=!0;const t=this._getActionConfig(e,"hold_action");"none"!==t.action&&this._handleAction(t,i)},500)}),t.addEventListener("pointerup",()=>clearTimeout(s)),t.addEventListener("pointercancel",()=>{clearTimeout(s),r=!1}),t.addEventListener("click",()=>{if(r)return void(r=!1);const t=this._getActionConfig(e,"double_tap_action");if(!t||"none"===t.action)return void this._handleAction(this._getActionConfig(e,"tap_action"),i);const s=Date.now();s-a<300?(clearTimeout(o),a=0,this._handleAction(t,i)):(a=s,o=setTimeout(()=>{a=0,this._handleAction(this._getActionConfig(e,"tap_action"),i)},300))})}_getActionConfig(t,e){const i=this._entities;if(!i)return{action:"tap_action"===e?"more-info":"none"};let s;if(t.startsWith("device_")){const e=parseInt(t.split("_")[1]);s=i.individual?.[e]}else{s={solar:i.solar,battery:i.battery,grid:i.grid,home:i.home,ev:i.ev||i.individual?.[0]}[t]}const r=s?.[e];return r?"string"==typeof r?{action:r}:r:{action:"tap_action"===e?"more-info":"none"}}_handleAction(t,e){switch(t||(t={action:"more-info"}),t.action){case"more-info":this._fireMoreInfo(t.entity||e);break;case"toggle":this._hass&&this._hass.callService("homeassistant","toggle",{entity_id:t.entity||e});break;case"navigate":t.navigation_path&&(window.history.pushState(null,"",t.navigation_path),window.dispatchEvent(new CustomEvent("location-changed")));break;case"call-service":if(t.service&&this._hass){const[e,i]=t.service.split(".");this._hass.callService(e,i,t.service_data||{})}break;case"url":t.url_path&&window.open(t.url_path,"_blank")}}_fireMoreInfo(t){t&&this.dispatchEvent(new CustomEvent("hass-more-info",{detail:{entityId:t},bubbles:!0,composed:!0}))}_setGlowIntensity(t,e,i){const s=this.renderRoot.querySelector(`#${t} .glow-ring`);if(!s)return;const r=Math.min(1,Math.abs(e)/i);s.style.opacity=(.15+.85*r).toFixed(2)}_animateValue(t,e,i=800,s=null){const r=this.renderRoot.getElementById(t);if(!r)return;this._animFrames[t]&&cancelAnimationFrame(this._animFrames[t]);const a=s||(t=>ht(t)),o=this._currentValues[t]||0;if(this._currentValues[t]=e,Math.abs(o-e)<.5)return void(r.textContent=a(e));const n=performance.now(),l=s=>{const c=Math.min(1,(s-n)/i),d=c<.5?2*c*c:1-Math.pow(-2*c+2,2)/2;r.textContent=a(o+(e-o)*d),c<1?this._animFrames[t]=requestAnimationFrame(l):delete this._animFrames[t]};this._animFrames[t]=requestAnimationFrame(l)}_setText(t,e){const i=this.renderRoot.getElementById(t);i&&(i.textContent=e)}_getState(t){if(!this._hass)return 0;const e="prefix"===this._mode?`${this._prefix}${t}`:this._resolveEntity(t);if(!e)return 0;const i=this._hass.states[e];if(!i)return 0;const s=parseFloat(i.state);return isNaN(s)?0:s}_getStateStr(t){if(!this._hass)return"";const e="prefix"===this._mode?`${this._prefix}${t}`:this._resolveEntity(t);if(!e)return"";const i=this._hass.states[e];return i?i.state:""}_getEntityId(t){return"prefix"===this._mode?`${this._prefix}${t}`:this._resolveEntity(t)}_resolveEntity(t){const e=this._entities;if(!e)return null;return{solar_power:e.solar?.entity,battery_power:e.battery?.entity,battery_charge_power:e.battery?.charge,battery_discharge_power:e.battery?.discharge,grid_power:e.grid?.entity,grid_import_power:e.grid?.consumption,grid_export_power:e.grid?.production,ev_power:e.ev?.entity||e.individual?.[0]?.entity,battery_soc:e.battery?.state_of_charge,home_consumption_power:e.home?.entity,charging_state:e.inverter?.entity,daily_solar_energy:e.solar?.daily_energy,daily_ev_energy:e.ev?.daily_energy||e.individual?.[0]?.daily_energy,daily_grid_import_energy:e.grid?.daily_import_energy,daily_grid_export_energy:e.grid?.daily_export_energy,daily_battery_energy:e.battery?.daily_energy,daily_home_energy:e.home?.daily_energy,autarky_rate:e.home?.autarky,ev_charger_count:e.ev?.charger_count||"sensor.sem_ev_charger_count"}[t]||null}_hasNode(t){if("prefix"===this._mode)return!0;const e=this._entities;if(!e)return!1;return{solar:!!e.solar?.entity,battery:!!(e.battery?.entity||e.battery?.charge||e.battery?.discharge),grid:!(!e.grid?.consumption&&!e.grid?.entity),home:!0,ev:!(!e.ev?.entity&&!e.individual?.[0]?.entity),inverter:!!e.inverter?.entity||!!e.solar?.entity}[t]||!1}_getNodeColor(t){const e=this._entities,i={solar:fe.solar.color,battery:fe.battery.color,grid:fe.grid.color_import,grid_import:fe.grid.color_import,grid_export:fe.grid.color_export,home:fe.home.color,ev:fe.ev.color,inverter:fe.inverter.color};if(!e)return i[t]||"#888";return{solar:e.solar?.color,battery:e.battery?.color,grid:e.grid?.color_import,grid_import:e.grid?.color_import,grid_export:e.grid?.color_export,home:e.home?.color,ev:e.ev?.color||e.individual?.[0]?.color}[t]||i[t]||"#888"}_getNodeName(t){const e=this._entities,i=fe[t]?.nameKey,s=i?this._t(i):t;if(!e)return s;return{solar:e.solar?.name,battery:e.battery?.name,grid:e.grid?.name,home:e.home?.name,ev:e.ev?.name||e.individual?.[0]?.name}[t]||s}_getLayout(){return this._compact?{vb:"0 0 500 1100",solar:{cx:250,cy:70,r:48},inverter:{cx:250,cy:225,r:20},battery:{cx:100,cy:340,r:48},grid:{cx:400,cy:340,r:48},home:{cx:250,cy:510,r:60},ev:{cx:100,cy:660,r:42},socR:33,autarkyR:48,paths:{solar:"M250,118 L250,205",home:"M250,245 L250,450",battery:"M230,230 C180,260 120,290 100,292",grid:"M270,230 C320,260 380,290 400,292",ev:"M230,240 C180,380 130,560 100,618"},font:{label:14,value:22,sub:12,homeVal:26},deviceY:810}:{vb:"0 0 1000 800",solar:{cx:500,cy:65,r:50},inverter:{cx:500,cy:210,r:20},battery:{cx:150,cy:270,r:50},grid:{cx:850,cy:270,r:50},home:{cx:500,cy:385,r:62},ev:{cx:150,cy:460,r:44},socR:40,autarkyR:50,paths:{solar:"M500,115 L500,190",home:"M500,230 L500,323",battery:"M480,215 C380,230 250,245 200,270",grid:"M520,215 C620,230 750,245 800,270",ev:"M480,225 C380,330 250,410 195,460"},font:{label:13,value:20,sub:11,homeVal:24},deviceY:590}}_glowFilter(t,e,i){return`<filter id="${t}" x="-30%" y="-30%" width="160%" height="160%">\n            <feGaussianBlur stdDeviation="${i}" result="blur"/>\n            <feFlood flood-color="${e}" flood-opacity="0.25"/>\n            <feComposite in2="blur" operator="in"/>\n            <feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge>\n        </filter>`}_glowRing(t,e,i=1.2){const s=t.r+5;return`<circle class="glow-ring" cx="${t.cx}" cy="${t.cy}" r="${s}" fill="none" stroke="${e}" stroke-width="${i}" opacity="0.3">\n            <animate attributeName="r" values="${s};${s+5};${s}" dur="3s" repeatCount="indefinite"/>\n            <animate attributeName="opacity" values="0.3;0.12;0.3" dur="3s" repeatCount="indefinite"/>\n        </circle>`}_track(t,e){return`<path d="${t}" fill="none" stroke="${e}" stroke-width="1.5" stroke-dasharray="4,6" opacity="0.18"/>`}_hexToRgba(t,e){const i=t.match(/^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i);return i?`rgba(${parseInt(i[1],16)},${parseInt(i[2],16)},${parseInt(i[3],16)},${e})`:`rgba(128,128,128,${e})`}_autarkyColor(t){if((t=Math.max(0,Math.min(100,t)))<=50){const e=t/50;return`rgb(220,${Math.round(50+150*e)},50)`}const e=(t-50)/50;return`rgb(${Math.round(220-170*e)},200,50)`}_deviceIcon(t,e){const i=(e||"").toLowerCase();return"ev_charger"===(t||"").toLowerCase()||i.includes("keba")||i.includes("charger")||i.includes("wallbox")?'<rect x="-6" y="-10" width="12" height="16" rx="2"/><path d="M-2,-4 L0,2 L2,-4"/><line x1="0" y1="6" x2="0" y2="10"/>':i.includes("heiz")||i.includes("heat")||i.includes("warm")||i.includes("boiler")?'<path d="M-4,-10 C-4,-4 4,-4 4,-10"/><path d="M-4,-3 C-4,3 4,3 4,-3"/><path d="M-4,4 C-4,10 4,10 4,4"/>':i.includes("wash")||i.includes("spül")||i.includes("geschirr")||i.includes("wasch")?'<circle r="10" fill="none"/><circle r="5" fill="none"/><circle r="1.5" fill="currentColor" opacity="0.3" stroke="none"/>':i.includes("dryer")||i.includes("trockn")?'<circle r="10" fill="none"/><path d="M-4,-4 C0,-8 0,8 4,4" fill="none"/>':i.includes("pool")||i.includes("pump")?'<circle r="8" fill="none"/><path d="M-6,0 L6,0 M0,-6 L0,6" opacity="0.5"/><path d="M-4,-4 L4,4 M4,-4 L-4,4"/>':i.includes("klima")||i.includes("ac")||i.includes("cool")||i.includes("air")?'<rect x="-10" y="-6" width="20" height="12" rx="2"/><path d="M-6,6 C-6,10 -2,10 -2,6" fill="none"/><path d="M2,6 C2,10 6,10 6,6" fill="none"/>':i.includes("light")||i.includes("licht")||i.includes("lamp")?'<path d="M-5,-10 C-8,-2 -3,4 -2,6 L2,6 C3,4 8,-2 5,-10 C2,-14 -2,-14 -5,-10Z" fill="none"/><line x1="-2" y1="8" x2="2" y2="8"/>':i.includes("shelly")||i.includes("plug")||i.includes("switch")||i.includes("steckdose")?'<rect x="-8" y="-10" width="16" height="20" rx="3"/><circle cx="-3" cy="-2" r="2" fill="none"/><circle cx="3" cy="-2" r="2" fill="none"/><line x1="0" y1="4" x2="0" y2="7"/>':'<path d="M-3,-10 L-3,0 L-6,0 L0,10 L0,0 L3,0 L-3,-10Z" fill="none"/>'}getCardSize(){return 8}static async getConfigElement(){return document.createElement("sem-flow-card-editor")}static getStubConfig(t){const e=t?Object.keys(t.states):[],i=t=>{for(const i of t){const t=e.find(t=>t.includes(i));if(t)return t}return null};return{entities:{solar:{entity:i(["solar_power","pv_power"])||"sensor.solar_power"},grid:{consumption:i(["grid_import","grid_consumption"])||"sensor.grid_import_power",production:i(["grid_export","grid_feed"])||"sensor.grid_export_power"},battery:{entity:i(["battery_power","batt_power"])||"sensor.battery_power",state_of_charge:i(["battery_soc","battery_level"])||"sensor.battery_soc"},home:{entity:i(["home_consumption","house_power"])||"sensor.home_consumption_power"}}}}},{type:"sem-flow-card",name:"SEM Flow Card",description:"Animated energy flow diagram — works with any HA entities"});yt("sem-system-diagram-card",class extends xt{constructor(){super(),this._lastKey="",this._animFrames={},this._currentValues={},this._compact=!1,this._visible=!0,this._updateTimer=null,this._resizeObserver=null,this._intersectionObserver=null,this._resizeTimeout=null}setConfig(t){this._config=t,this.entityPrefix=t.entity_prefix||"sensor.sem_",this.requestUpdate()}set hass(t){this._hass=t;const e=t?.language;if(e!==this._lang)return this._lang=e,this._lastKey="",void this.requestUpdate();const i=ft(t,this._prefix);if(i!==this._lastPVKey)return this._lastPVKey=i,void this.requestUpdate();this._visible&&(clearTimeout(this._updateTimer),this._updateTimer=setTimeout(()=>this._updateFlowsImperative(),100))}get hass(){return this._hass}firstUpdated(){this._resizeObserver=new ResizeObserver(t=>{this._resizeTimeout&&clearTimeout(this._resizeTimeout),this._resizeTimeout=setTimeout(()=>{for(const e of t){const t=e.contentRect.width<500;t!==this._compact&&(this._compact=t,this._lastKey="",this.requestUpdate())}},100)}),this._resizeObserver.observe(this),this._intersectionObserver=new IntersectionObserver(t=>{this._visible=t[0].isIntersecting;const e=this.renderRoot.querySelector("svg");e&&(e.style.animationPlayState=this._visible?"running":"paused")},{threshold:.01}),this._intersectionObserver.observe(this)}disconnectedCallback(){super.disconnectedCallback(),this._resizeObserver&&(this._resizeObserver.disconnect(),this._resizeObserver=null),this._intersectionObserver&&(this._intersectionObserver.disconnect(),this._intersectionObserver=null),clearTimeout(this._updateTimer),clearTimeout(this._resizeTimeout);for(const t of Object.keys(this._animFrames))cancelAnimationFrame(this._animFrames[t]);this._animFrames={}}updated(){super.updated(),this._updateFlowsImperative()}static get styles(){return a`
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
        `}render(){if(!this._config)return K;const t=this._getLayout(),e=this._compact,i="'Segoe UI','Roboto',sans-serif",s=t.font.label,r=t.font.value,a=t.font.sub,o=mt(this._hass,this._prefix);return W`
            <ha-card>
                <style>${vt}</style>
                ${o.length>=2?W`
                    <div class="pv-strings-row">
                        ${o.map(t=>W`
                            <div class="pv-chip"
                                 title="${t.entityId}"
                                 data-entity="${t.entityId}"
                                 @click=${()=>this._fireMoreInfo?.(t.entityId)}>
                                <span class="pv-chip-label">PV${t.slot.replace(/^pv/,"")}</span>
                                <span class="pv-chip-value">${(Math.abs(t.watts)/1e3).toFixed(2)} kW</span>
                            </div>
                        `)}
                    </div>
                `:K}
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="${t.vb}"
                     style="background:transparent;overflow:hidden"
                     role="img" aria-label="Solar energy system power flow diagram">
                    <defs>
                        <!-- Background gradient -->
                        <radialGradient id="bgGrad" cx="50%" cy="40%" r="65%">
                            <stop offset="0%" stop-color="rgba(150,202,238,0.06)"/>
                            <stop offset="100%" stop-color="rgba(0,0,0,0)"/>
                        </radialGradient>
                        <!-- Dot grid pattern -->
                        <pattern id="dotGrid" width="40" height="40" patternUnits="userSpaceOnUse">
                            <circle cx="20" cy="20" r="0.6" fill="rgba(128,128,128,0.07)"/>
                        </pattern>

                        <!-- Glow filters -->
                        ${this._glowFilter("glowSolar","#ff9800",10)}
                        ${this._glowFilter("glowBattery","#4db6ac",8)}
                        ${this._glowFilter("glowGrid","#488fc2",8)}
                        ${this._glowFilter("glowHome","#5BC8D8",12)}
                        ${this._glowFilter("glowEV","#8DC892",8)}
                        ${this._glowFilter("glowInverter","#96CAEE",6)}
                        ${this._glowFilter("glowSun","#FCD170",14)}

                        <!-- Solar panel cell gradient -->
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

                        <!-- Battery gradient -->
                        <linearGradient id="battBody" x1="0%" y1="0%" x2="100%" y2="0%">
                            <stop offset="0%" stop-color="#1a2e2c"/>
                            <stop offset="100%" stop-color="#1f3835"/>
                        </linearGradient>
                        <linearGradient id="battFillGrad" x1="0%" y1="100%" x2="0%" y2="0%">
                            <stop offset="0%" stop-color="#4db6ac"/>
                            <stop offset="100%" stop-color="#80cbc4"/>
                        </linearGradient>

                        <!-- House roof gradient -->
                        <linearGradient id="roofGrad" x1="0%" y1="0%" x2="0%" y2="100%">
                            <stop offset="0%" stop-color="#c62828"/>
                            <stop offset="100%" stop-color="#b71c1c"/>
                        </linearGradient>
                        <!-- House wall gradient -->
                        <linearGradient id="wallGrad" x1="0%" y1="0%" x2="0%" y2="100%">
                            <stop offset="0%" stop-color="#37474F"/>
                            <stop offset="100%" stop-color="#263238"/>
                        </linearGradient>
                        <!-- Window glow gradient -->
                        <radialGradient id="windowGlow" cx="50%" cy="50%" r="50%">
                            <stop offset="0%" stop-color="#FFF9C4" stop-opacity="0.9"/>
                            <stop offset="100%" stop-color="#F9A825" stop-opacity="0.3"/>
                        </radialGradient>

                        <!-- Grid pole gradient -->
                        <linearGradient id="poleGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                            <stop offset="0%" stop-color="#5c7a9b"/>
                            <stop offset="50%" stop-color="#6d8fad"/>
                            <stop offset="100%" stop-color="#5c7a9b"/>
                        </linearGradient>

                        <!-- Inverter box gradient -->
                        <linearGradient id="invGrad" x1="0%" y1="0%" x2="0%" y2="100%">
                            <stop offset="0%" stop-color="#1a2740"/>
                            <stop offset="100%" stop-color="#0f1820"/>
                        </linearGradient>

                        <!-- EV car body gradient -->
                        <linearGradient id="carGrad" x1="0%" y1="0%" x2="0%" y2="100%">
                            <stop offset="0%" stop-color="#2e5a3c"/>
                            <stop offset="100%" stop-color="#1b3b27"/>
                        </linearGradient>

                        <!-- Sun glow radial -->
                        <radialGradient id="sunGradInner" cx="50%" cy="50%" r="50%">
                            <stop offset="0%" stop-color="#FFF9C4"/>
                            <stop offset="60%" stop-color="#FCD170"/>
                            <stop offset="100%" stop-color="#F7941E"/>
                        </radialGradient>

                        <!-- Flow paths (referenced by animateMotion) -->
                        <path id="path-solar"   d="${t.paths.solar}"/>
                        <path id="path-home"    d="${t.paths.home}"/>
                        <path id="path-battery" d="${t.paths.battery}"/>
                        <path id="path-grid"    d="${t.paths.grid}"/>
                        <path id="path-ev"      d="${t.paths.ev}"/>
                    </defs>

                    <!-- Background -->
                    <rect width="100%" height="100%" fill="url(#bgGrad)"/>
                    <rect width="100%" height="100%" fill="url(#dotGrid)"/>

                    <!-- ══════════════════════════════════════════════
                         SUN ARC (top decorative element)
                         Positioned along arc, moves with solar position
                    ══════════════════════════════════════════════ -->
                    <g id="sun-arc-group">
                        <!-- Arc track -->
                        <path id="sun-arc-path" d="${t.sunArc}" fill="none" stroke="rgba(252,209,112,0.12)"
                              stroke-width="2" stroke-dasharray="4,8"/>
                        <!-- Rising time label -->
                        <text id="sun-rising" x="${t.sunRisingX}" y="${t.sunLabelY}"
                              text-anchor="middle" font-family="${i}" font-size="${a}"
                              fill="#FCD170" opacity="0.45"></text>
                        <!-- Setting time label -->
                        <text id="sun-setting" x="${t.sunSettingX}" y="${t.sunLabelY}"
                              text-anchor="middle" font-family="${i}" font-size="${a}"
                              fill="#FCD170" opacity="0.45"></text>
                        <!-- Sun disc — position updated imperatively -->
                        <g id="sun-glow" filter="url(#glowSun)" style="opacity:0.85">
                            <!-- Outer warm halo -->
                            <circle id="sun-circle" cx="${t.sunX}" cy="${t.sunY}" r="${t.sunR+6}"
                                    fill="rgba(252,209,112,0.15)"/>
                            <!-- Ray spikes (8 rays) — drawn around center -->
                            ${this._sunRays(t.sunX,t.sunY,t.sunR)}
                            <!-- Core disc -->
                            <circle cx="${t.sunX}" cy="${t.sunY}" r="${t.sunR}"
                                    fill="url(#sunGradInner)"/>
                            <!-- Highlight -->
                            <ellipse cx="${t.sunX-.25*t.sunR}" cy="${t.sunY-.28*t.sunR}"
                                     rx="${.35*t.sunR}" ry="${.22*t.sunR}"
                                     fill="rgba(255,255,255,0.35)"/>
                        </g>
                        <!-- Moon (shown at night) -->
                        <g id="moon-crescent" style="display:none">
                            <circle cx="${t.sunX}" cy="${t.sunY}" r="${t.sunR}"
                                    fill="#1a2540"/>
                            <circle cx="${t.sunX+.38*t.sunR}" cy="${t.sunY-.22*t.sunR}"
                                    r="${.78*t.sunR}" fill="#0d1a30"/>
                            <circle cx="${t.sunX}" cy="${t.sunY}" r="${t.sunR}"
                                    fill="none" stroke="rgba(200,220,255,0.5)" stroke-width="1"/>
                        </g>
                        <!-- Stars (shown at night) -->
                        <g id="stars" style="display:none" fill="rgba(200,220,255,0.6)">
                            <circle cx="${t.starX[0]}" cy="${t.starY[0]}" r="1.2"/>
                            <circle cx="${t.starX[1]}" cy="${t.starY[1]}" r="0.9"/>
                            <circle cx="${t.starX[2]}" cy="${t.starY[2]}" r="1.4"/>
                            <circle cx="${t.starX[3]}" cy="${t.starY[3]}" r="0.8"/>
                            <circle cx="${t.starX[4]}" cy="${t.starY[4]}" r="1.1"/>
                        </g>
                        <!-- Solar power label on sun -->
                        <text id="sun-power-label" x="${t.sunX}" y="${t.sunY+t.sunR+14}"
                              text-anchor="middle" font-family="${i}" font-size="${a}"
                              fill="#FCD170" opacity="0.7" font-weight="600"></text>

                        <!-- Sun-to-solar energy wave (populated imperatively) -->
                        <g id="sun-spark" style="opacity:0"></g>
                    </g>

                    <!-- ══════════════════════════════════════════════
                         FLOW TRACKS (static dashed paths)
                    ══════════════════════════════════════════════ -->
                    <path d="${t.paths.solar}"   fill="none" stroke="#ff9800" stroke-width="2"
                          stroke-dasharray="5,7" opacity="0.22"/>
                    <path d="${t.paths.home}"    fill="none" stroke="#5BC8D8" stroke-width="2"
                          stroke-dasharray="5,7" opacity="0.22"/>
                    <path d="${t.paths.battery}" fill="none" stroke="#4db6ac" stroke-width="2"
                          stroke-dasharray="5,7" opacity="0.22"/>
                    <path d="${t.paths.grid}"    fill="none" stroke="#488fc2" stroke-width="2"
                          stroke-dasharray="5,7" opacity="0.22"/>
                    <path d="${t.paths.ev}"      fill="none" stroke="#8DC892" stroke-width="2"
                          stroke-dasharray="5,7" opacity="0.22"/>

                    <!-- ══════════════════════════════════════════════
                         FLOW ANIMATION GROUPS
                    ══════════════════════════════════════════════ -->
                    <g id="flow-solar"   class="flow-group" style="opacity:0"
                       data-path-id="path-solar"   data-path-d="${t.paths.solar}"
                       data-color="#ff9800" data-count="2"></g>
                    <g id="flow-battery" class="flow-group" style="opacity:0"
                       data-path-id="path-battery" data-path-d="${t.paths.battery}"
                       data-color="#4db6ac" data-count="3"></g>
                    <g id="flow-grid"    class="flow-group" style="opacity:0"
                       data-path-id="path-grid"    data-path-d="${t.paths.grid}"
                       data-color="#488fc2" data-count="3"></g>
                    <g id="flow-home"    class="flow-group" style="opacity:0"
                       data-path-id="path-home"    data-path-d="${t.paths.home}"
                       data-color="#5BC8D8" data-count="2"></g>
                    <g id="flow-ev"      class="flow-group" style="opacity:0"
                       data-path-id="path-ev"      data-path-d="${t.paths.ev}"
                       data-color="#8DC892" data-count="3"></g>

                    <!-- ══════════════════════════════════════════════
                         SOLAR PANELS ILLUSTRATION
                    ══════════════════════════════════════════════ -->
                    <g id="node-solar" filter="url(#glowSolar)" class="clickable" @click=${()=>this._showMoreInfo("solar_power")}>
                        ${this._illustrationSolarPanel(t.S.cx,t.S.cy,t.S.r)}
                    </g>
                    <text x="${t.S.cx}" y="${t.S.labelY}" text-anchor="middle"
                          font-family="${i}" font-size="${s}" font-weight="700"
                          fill="#ff9800" letter-spacing="0.5">${this._t("solar")}</text>
                    <text id="val-solar" x="${t.S.cx}" y="${t.S.labelY+1.1*r}" class="clickable"
                          @click=${()=>this._showMoreInfo("solar_power")}
                          text-anchor="middle" font-family="${i}" font-size="${r}"
                          font-weight="800" fill="#ff9800">0 W</text>
                    <text id="val-solar-kwh" x="${t.S.cx}" y="${t.S.labelY+1.1*r+a+3}" class="clickable"
                          @click=${()=>this._showMoreInfo("daily_solar_energy")}
                          text-anchor="middle" font-family="${i}" font-size="${a+1}"
                          fill="#ff9800" opacity="0.6" font-weight="600"></text>
                    <text id="val-solar-forecast" x="${t.S.cx}" y="${t.S.labelY+1.1*r+2*(a+3)}" class="clickable"
                          @click=${()=>this._showMoreInfo("forecast_corrected_today")}
                          text-anchor="middle" font-family="${i}" font-size="${a}"
                          fill="#ff9800" opacity="0.4" font-weight="500"></text>

                    <!-- ══════════════════════════════════════════════
                         INVERTER ILLUSTRATION
                    ══════════════════════════════════════════════ -->
                    <g id="node-inverter" filter="url(#glowInverter)">
                        ${this._illustrationInverter(t.I.cx,t.I.cy,t.I.r)}
                    </g>
                    <text id="val-inv-temp" x="${t.I.cx}" y="${t.I.cy+t.I.r+14}"
                          text-anchor="middle" font-family="${i}" font-size="${a}"
                          fill="#96CAEE" opacity="0.6" font-weight="600"></text>
                    <text id="val-inv-status" x="${t.I.cx}" y="${t.I.cy+t.I.r+14+a+2}"
                          text-anchor="middle" font-family="${i}" font-size="${a-1}"
                          fill="#96CAEE" opacity="0.35"></text>

                    <!-- ══════════════════════════════════════════════
                         BATTERY ILLUSTRATION
                    ══════════════════════════════════════════════ -->
                    <g id="node-battery" filter="url(#glowBattery)" class="clickable" @click=${()=>this._showMoreInfo("battery_soc")}>
                        ${this._illustrationBattery(t.B.cx,t.B.cy,t.B.r)}
                    </g>
                    <text x="${t.B.cx}" y="${t.B.labelY}" text-anchor="middle"
                          font-family="${i}" font-size="${s}" font-weight="700"
                          fill="#4db6ac" letter-spacing="0.5">${this._t("battery")}</text>
                    <text id="val-batt-power" x="${t.B.cx}" y="${t.B.labelY+1*r}" class="clickable"
                          @click=${()=>this._showMoreInfo("battery_power")}
                          text-anchor="middle" font-family="${i}" font-size="${r}"
                          font-weight="800" fill="#4db6ac">0 W</text>
                    <text id="label-batt-state" x="${t.B.cx}" y="${t.B.labelY+1*r+s}"
                          text-anchor="middle" font-family="${i}" font-size="${s}"
                          fill="#4db6ac" opacity="0.6"></text>
                    <text id="val-batt-kwh" x="${t.B.cx}" y="${t.B.labelY+1*r+s+a+2}" class="clickable"
                          @click=${()=>this._showMoreInfo("daily_battery_charge_energy")}
                          text-anchor="middle" font-family="${i}" font-size="${a+1}"
                          fill="#4db6ac" opacity="0.6" font-weight="600"></text>
                    </g>

                    <!-- ══════════════════════════════════════════════
                         GRID / POWER POLE ILLUSTRATION
                    ══════════════════════════════════════════════ -->
                    <g id="node-grid" filter="url(#glowGrid)" class="clickable" @click=${()=>this._showMoreInfo("grid_import_power")}>
                        ${this._illustrationGrid(t.G.cx,t.G.cy,t.G.r)}
                    </g>
                    <text id="label-grid" x="${t.G.cx}" y="${t.G.labelY}" text-anchor="middle"
                          font-family="${i}" font-size="${s}" font-weight="700"
                          fill="#488fc2" letter-spacing="0.5">${this._t("grid")}</text>
                    <text id="val-grid-single" x="${t.G.cx}" y="${t.G.labelY+r}" class="clickable"
                          @click=${()=>this._showMoreInfo("grid_power")}
                          text-anchor="middle" font-family="${i}" font-size="${r}"
                          font-weight="800" fill="#488fc2">0 W</text>
                    <text id="label-grid-state" x="${t.G.cx}" y="${t.G.labelY+r+s+1}"
                          text-anchor="middle" font-family="${i}" font-size="${s}"
                          fill="#488fc2" opacity="0.6"></text>
                    <text id="val-grid-kwh" x="${t.G.cx}" y="${t.G.labelY+r+s+a+4}" class="clickable"
                          @click=${()=>this._showMoreInfo("daily_grid_import_energy")}
                          text-anchor="middle" font-family="${i}" font-size="${a+1}"
                          fill="#488fc2" opacity="0.6" font-weight="600"></text>

                    <!-- ══════════════════════════════════════════════
                         HOUSE ILLUSTRATION
                    ══════════════════════════════════════════════ -->
                    <g id="node-home" filter="url(#glowHome)" class="clickable" @click=${()=>this._showMoreInfo("home_consumption_power")}>
                        ${this._illustrationHouse(t.H.cx,t.H.cy,t.H.r)}
                    </g>
                    <text x="${t.H.cx}" y="${t.H.labelY}" text-anchor="middle"
                          font-family="${i}" font-size="${s}" font-weight="700"
                          fill="#5BC8D8" letter-spacing="0.5">${this._t("home")}</text>
                    <text id="val-home" x="${t.H.cx}" y="${t.H.labelY+1.1*r}" class="clickable"
                          @click=${()=>this._showMoreInfo("home_consumption_power")}
                          text-anchor="middle" font-family="${i}" font-size="${r}"
                          font-weight="800" fill="#5BC8D8">0 W</text>
                    <text id="val-home-kwh" x="${t.H.cx}" y="${t.H.labelY+1.1*r+a+3}" class="clickable"
                          @click=${()=>this._showMoreInfo("daily_home_energy")}
                          text-anchor="middle" font-family="${i}" font-size="${a+1}"
                          fill="#5BC8D8" opacity="0.6" font-weight="600"></text>

                    <!-- ══════════════════════════════════════════════
                         EV CHARGER ILLUSTRATION
                    ══════════════════════════════════════════════ -->
                    <g id="node-ev" filter="url(#glowEV)" class="clickable" @click=${()=>this._showMoreInfo("ev_power")}>
                        ${this._illustrationEV(t.E.cx,t.E.cy,t.E.r)}
                    </g>
                    <text x="${t.E.cx}" y="${t.E.labelY}" text-anchor="middle"
                          font-family="${i}" font-size="${s}" font-weight="700"
                          fill="#8DC892" letter-spacing="0.5">${this._t("ev_charging")}</text>
                    <text id="val-ev" x="${t.E.cx}" y="${t.E.labelY+1*r}" class="clickable"
                          @click=${()=>this._showMoreInfo("ev_power")}
                          text-anchor="middle" font-family="${i}" font-size="${r}"
                          font-weight="800" fill="#8DC892">0 W</text>
                    <text id="label-ev-state" x="${t.E.cx}" y="${t.E.labelY+1*r+s}"
                          text-anchor="middle" font-family="${i}" font-size="${s}"
                          fill="#8DC892" opacity="0.6"></text>
                    <text id="val-ev-kwh" x="${t.E.cx}" y="${t.E.labelY+1*r+s+a+2}" class="clickable"
                          @click=${()=>this._showMoreInfo("daily_ev_energy")}
                          text-anchor="middle" font-family="${i}" font-size="${a+1}"
                          fill="#8DC892" opacity="0.6" font-weight="600"></text>

                    <!-- Device labels (populated imperatively) -->
                    <g id="device-labels"></g>

                    <!-- Entity status indicator -->
                    <foreignObject x="${e?8:10}" y="${t.statusY}" width="220" height="22">
                        <div xmlns="http://www.w3.org/1999/xhtml" id="entity-status"
                             style="display:none;font-family:'Segoe UI','Roboto',sans-serif;font-size:10px;color:#ef5350;opacity:0.75;white-space:nowrap"></div>
                    </foreignObject>

                    <!-- SEM watermark -->
                    <text x="${t.wmX}" y="${t.wmY}" text-anchor="end"
                          font-family="${i}" font-size="9" font-weight="300"
                          letter-spacing="2.5" fill="rgba(255,255,255,0.06)">SEM</text>
                </svg>
            </ha-card>
        `}_illustrationSolarPanel(t,e,i){const s=i/50,r=86*s,a=58*s,o=t-r/2,n=e-a/2-4*s,l=r/3,c=a/2,d=6*s,p=12*s;return j`
            <!-- Outer glow halo -->
            <circle cx="${t}" cy="${e}" r="${i+4}" fill="none"
                    stroke="#ff9800" stroke-width="1.2" opacity="0.25"/>

            <!-- Mounting structure frame -->
            <line x1="${o+d}" y1="${n+a}" x2="${o+d-4*s}" y2="${n+a+p}"
                  stroke="#ff9800" stroke-width="${2*s}" stroke-linecap="round" opacity="0.7"/>
            <line x1="${o+r-d}" y1="${n+a}" x2="${o+r-d+4*s}" y2="${n+a+p}"
                  stroke="#ff9800" stroke-width="${2*s}" stroke-linecap="round" opacity="0.7"/>
            <line x1="${o+r/2}" y1="${n+a}" x2="${o+r/2}" y2="${n+a+.8*p}"
                  stroke="#ff9800" stroke-width="${1.5*s}" stroke-linecap="round" opacity="0.5"/>
            <!-- Ground bar -->
            <line x1="${o+d-6*s}" y1="${n+a+p}"
                  x2="${o+r-d+6*s}" y2="${n+a+p}"
                  stroke="#ff9800" stroke-width="${2.5*s}" stroke-linecap="round" opacity="0.6"/>

            <!-- Rail behind panels -->
            <line x1="${o}" y1="${n+.52*a}" x2="${o+r}" y2="${n+.52*a}"
                  stroke="#ff9800" stroke-width="${2*s}" opacity="0.5"/>
            <line x1="${o}" y1="${n}" x2="${o+r}" y2="${n}"
                  stroke="#ff9800" stroke-width="${2*s}" opacity="0.5"/>

            <!-- Panel cells: 3 cols x 2 rows alternating blue shades -->
            <rect x="${o}"        y="${n}"      width="${l}" height="${c}" fill="url(#panelBlue)"  rx="${1*s}"/>
            <rect x="${o+l}"   y="${n}"      width="${l}" height="${c}" fill="url(#panelBlue2)" rx="${1*s}"/>
            <rect x="${o+2*l}" y="${n}"      width="${l}" height="${c}" fill="url(#panelBlue)"  rx="${1*s}"/>
            <rect x="${o}"        y="${n+c}" width="${l}" height="${c}" fill="url(#panelBlue2)" rx="${1*s}"/>
            <rect x="${o+l}"   y="${n+c}" width="${l}" height="${c}" fill="url(#panelBlue)"  rx="${1*s}"/>
            <rect x="${o+2*l}" y="${n+c}" width="${l}" height="${c}" fill="url(#panelBlue2)" rx="${1*s}"/>

            <!-- Panel divider lines (vertical) -->
            <line x1="${o+l}"   y1="${n}" x2="${o+l}"   y2="${n+a}" stroke="rgba(0,0,0,0.4)" stroke-width="${1.5*s}"/>
            <line x1="${o+2*l}" y1="${n}" x2="${o+2*l}" y2="${n+a}" stroke="rgba(0,0,0,0.4)" stroke-width="${1.5*s}"/>
            <!-- Panel divider line (horizontal) -->
            <line x1="${o}" y1="${n+c}" x2="${o+r}" y2="${n+c}" stroke="rgba(0,0,0,0.4)" stroke-width="${1.5*s}"/>
            <!-- Inner cell lines (each panel has 2x3 micro-cells) -->
            ${[0,1,2].map(t=>j`
                <line x1="${o+t*l+l/3}"   y1="${n}" x2="${o+t*l+l/3}"   y2="${n+a}" stroke="rgba(0,0,0,0.2)" stroke-width="${.7*s}"/>
                <line x1="${o+t*l+2*l/3}" y1="${n}" x2="${o+t*l+2*l/3}" y2="${n+a}" stroke="rgba(0,0,0,0.2)" stroke-width="${.7*s}"/>
            `)}
            <line x1="${o}" y1="${n+c/3}"   x2="${o+r}" y2="${n+c/3}"   stroke="rgba(0,0,0,0.18)" stroke-width="${.7*s}"/>
            <line x1="${o}" y1="${n+2*c/3}" x2="${o+r}" y2="${n+2*c/3}" stroke="rgba(0,0,0,0.18)" stroke-width="${.7*s}"/>

            <!-- Outer panel border -->
            <rect x="${o}" y="${n}" width="${r}" height="${a}"
                  fill="none" stroke="#ff9800" stroke-width="${2*s}" rx="${1.5*s}" opacity="0.8"/>

            <!-- Reflective sheen overlay -->
            <rect x="${o}" y="${n}" width="${r}" height="${.45*a}"
                  fill="url(#panelReflect)" rx="${1.5*s}" opacity="0.5"/>

            <!-- Orange accent connector to inverter -->
            <circle cx="${t}" cy="${n+a+p+3*s}" r="${3*s}"
                    fill="#ff9800" opacity="0.6"/>
        `}_sunRays(t,e,i){const s=[];for(let r=0;r<8;r++){const a=45*r*Math.PI/180,o=i+3,n=i+.7*i,l=.18,c=a-l,d=a+l,p=t+Math.cos(c)*o,h=e+Math.sin(c)*o,_=t+Math.cos(a)*n,g=e+Math.sin(a)*n,u=t+Math.cos(d)*o,f=e+Math.sin(d)*o;s.push(j`<polygon points="${p},${h} ${_},${g} ${u},${f}"
                                    fill="#FCD170" opacity="0.85"/>`)}return s}_illustrationInverter(t,e,i){const s=i/20,r=38*s,a=28*s,o=t-r/2,n=e-a/2;return j`
            <!-- Box body -->
            <rect x="${o}" y="${n}" width="${r}" height="${a}" rx="${4*s}"
                  fill="url(#invGrad)" stroke="#96CAEE" stroke-width="${1.5*s}" opacity="0.9"/>
            <!-- Top vent lines -->
            ${[0,1,2].map(t=>j`
                <line x1="${o+4*s+5*t*s}" y1="${n+3*s}" x2="${o+4*s+5*t*s}" y2="${n+7*s}"
                      stroke="#96CAEE" stroke-width="${1*s}" stroke-linecap="round" opacity="0.4"/>
            `)}
            <!-- DC arrow -->
            <text x="${t-8*s}" y="${e+2*s}" font-family="'Segoe UI',sans-serif"
                  font-size="${7*s}" fill="#96CAEE" opacity="0.8" text-anchor="middle">DC</text>
            <!-- Lightning bolt symbol -->
            <path d="M${t-1*s},${e-4*s} L${t-3*s},${e+1*s} L${t},${e+1*s}
                     L${t},${e+5*s} L${t+2*s},${e} L${t-1*s},${e}"
                  fill="#FCD170" opacity="0.85"/>
            <!-- AC label -->
            <text x="${t+8*s}" y="${e+2*s}" font-family="'Segoe UI',sans-serif"
                  font-size="${7*s}" fill="#96CAEE" opacity="0.8" text-anchor="middle">AC</text>
            <!-- Status LED -->
            <circle cx="${o+r-5*s}" cy="${n+4*s}" r="${2.5*s}"
                    fill="#69f0ae" opacity="0.9">
                <animate attributeName="opacity" values="0.9;0.4;0.9" dur="2.5s" repeatCount="indefinite"/>
            </circle>
            <!-- Bottom connector nub -->
            <rect x="${t-3*s}" y="${n+a}" width="${6*s}" height="${3*s}" rx="${1*s}"
                  fill="#96CAEE" opacity="0.4"/>
        `}_illustrationBattery(t,e,i){const s=i/50,r=40*s,a=64*s,o=t-r/2,n=e-a/2,l=8*s,c=16*s,d=r-8*s,p=a-12*s,h=o+4*s,_=n+8*s;return j`
            <!-- Outer glow halo -->
            <circle cx="${t}" cy="${e}" r="${i+4}" fill="none"
                    stroke="#4db6ac" stroke-width="1.2" opacity="0.25"/>

            <!-- Terminal cap on top -->
            <rect x="${t-c/2}" y="${n-l}" width="${c}" height="${l}"
                  rx="${3*s}" fill="#2a4a47" stroke="#4db6ac" stroke-width="${1.5*s}" opacity="0.85"/>
            <!-- Plus terminal -->
            <line x1="${t-c/4}" y1="${n-l/2}"
                  x2="${t+c/4}" y2="${n-l/2}"
                  stroke="#4db6ac" stroke-width="${2*s}" stroke-linecap="round" opacity="0.8"/>
            <line x1="${t}" y1="${n-.75*l}" x2="${t}" y2="${n-.25*l}"
                  stroke="#4db6ac" stroke-width="${2*s}" stroke-linecap="round" opacity="0.8"/>

            <!-- Main body -->
            <rect x="${o}" y="${n}" width="${r}" height="${a}" rx="${5*s}"
                  fill="url(#battBody)" stroke="#4db6ac" stroke-width="${2*s}" opacity="0.95"/>

            <!-- Fill level background (empty) -->
            <rect x="${h}" y="${_}" width="${d}" height="${p}"
                  rx="${3*s}" fill="rgba(0,0,0,0.4)"/>

            <!-- Fill level bar — height controlled imperatively via id="batt-fill" -->
            <!-- Initial height = 0 (bottom-anchored, y+height = bottom of inner area) -->
            <rect id="batt-fill"
                  x="${h}" y="${_+p}"
                  width="${d}" height="0"
                  rx="${3*s}" fill="url(#battFillGrad)" opacity="0.85"/>

            <!-- Cell segmentation lines (5 horizontal ticks) -->
            ${[1,2,3,4].map(t=>j`
                <line x1="${h}" y1="${_+p*t/5}"
                      x2="${h+d}" y2="${_+p*t/5}"
                      stroke="rgba(0,0,0,0.35)" stroke-width="${1.2*s}"/>
            `)}

            <!-- SOC percentage text centered in body (with dark outline for contrast) -->
            <text id="batt-soc-text" x="${t}" y="${e+4*s}"
                  text-anchor="middle" font-family="'Segoe UI','Roboto',sans-serif"
                  font-size="${14*s}" font-weight="900" fill="#fff"
                  stroke="rgba(0,0,0,0.6)" stroke-width="${1.5*s}" paint-order="stroke">50%</text>

            <!-- Charging bolt icon (shown when charging) -->
            <g id="batt-bolt" style="display:none">
                <path d="M${t-4*s},${e-8*s} L${t-7*s},${e+2*s} L${t-1*s},${e+2*s}
                         L${t-1*s},${e+10*s} L${t+6*s},${e-2*s} L${t+1*s},${e-2*s} Z"
                      fill="#FCD170" opacity="0.9"/>
            </g>

            <!-- Bottom mount detail -->
            <rect x="${t-10*s}" y="${n+a-5*s}" width="${20*s}" height="${5*s}"
                  rx="${2*s}" fill="#4db6ac" opacity="0.25"/>
        `}_illustrationHouse(t,e,i){const s=i/62,r=80*s,a=52*s,o=t-r/2,n=e-a/2+8*s,l=n-38*s,c=t+18*s,d=l+8*s,p=10*s,h=18*s,_=16*s,g=14*s,u=n+12*s,f=o+10*s,m=o+r-10*s-_,v=14*s,y=24*s,x=t-v/2,b=n+a-y;return j`
            <!-- Outer glow halo -->
            <circle cx="${t}" cy="${e}" r="${i+4}" fill="none"
                    stroke="#5BC8D8" stroke-width="1.2" opacity="0.25"/>

            <!-- Chimney (behind roof) -->
            <rect x="${c}" y="${d-h}" width="${p}" height="${h}"
                  rx="${2*s}" fill="#455A64" stroke="#546E7A" stroke-width="${1.2*s}"/>
            <!-- Chimney smoke puffs -->
            <circle cx="${c+p/2}" cy="${d-h-5*s}" r="${3*s}"
                    fill="rgba(150,160,170,0.3)"/>
            <circle cx="${c+p/2+2*s}" cy="${d-h-10*s}" r="${2.5*s}"
                    fill="rgba(150,160,170,0.2)"/>

            <!-- Roof -->
            <polygon points="${o},${n} ${o+r},${n} ${t},${l}"
                     fill="url(#roofGrad)" stroke="#c62828" stroke-width="${1.5*s}"
                     stroke-linejoin="round"/>
            <!-- Roof ridge highlight -->
            <line x1="${t-18*s}" y1="${l+10*s}" x2="${t+18*s}" y2="${l+10*s}"
                  stroke="rgba(255,255,255,0.12)" stroke-width="${1*s}"/>
            <!-- Roof eaves overhang shadow -->
            <line x1="${o-3*s}" y1="${n}" x2="${o+r+3*s}" y2="${n}"
                  stroke="#7f1010" stroke-width="${3*s}" opacity="0.5"/>

            <!-- Wall body -->
            <rect x="${o}" y="${n}" width="${r}" height="${a}"
                  rx="${2*s}" fill="url(#wallGrad)"
                  stroke="#546E7A" stroke-width="${1.5*s}"/>

            <!-- Window 1 — left -->
            <!-- Window frame -->
            <rect x="${f-2*s}" y="${u-2*s}" width="${_+4*s}" height="${g+4*s}"
                  rx="${2*s}" fill="#2d3c45" stroke="#5BC8D8" stroke-width="${1.2*s}" opacity="0.9"/>
            <!-- Window glass with glow -->
            <rect x="${f}" y="${u}" width="${_}" height="${g}"
                  rx="${1.5*s}" fill="url(#windowGlow)" opacity="0.85"/>
            <!-- Window pane dividers -->
            <line x1="${f+_/2}" y1="${u}" x2="${f+_/2}" y2="${u+g}"
                  stroke="rgba(50,50,60,0.6)" stroke-width="${1.2*s}"/>
            <line x1="${f}" y1="${u+g/2}" x2="${f+_}" y2="${u+g/2}"
                  stroke="rgba(50,50,60,0.6)" stroke-width="${1.2*s}"/>

            <!-- Window 2 — right -->
            <rect x="${m-2*s}" y="${u-2*s}" width="${_+4*s}" height="${g+4*s}"
                  rx="${2*s}" fill="#2d3c45" stroke="#5BC8D8" stroke-width="${1.2*s}" opacity="0.9"/>
            <rect x="${m}" y="${u}" width="${_}" height="${g}"
                  rx="${1.5*s}" fill="url(#windowGlow)" opacity="0.85"/>
            <line x1="${m+_/2}" y1="${u}" x2="${m+_/2}" y2="${u+g}"
                  stroke="rgba(50,50,60,0.6)" stroke-width="${1.2*s}"/>
            <line x1="${m}" y1="${u+g/2}" x2="${m+_}" y2="${u+g/2}"
                  stroke="rgba(50,50,60,0.6)" stroke-width="${1.2*s}"/>

            <!-- Door -->
            <rect x="${x}" y="${b}" width="${v}" height="${y}"
                  rx="${2*s}" fill="#506C7F" stroke="#5BC8D8" stroke-width="${1.2*s}" opacity="0.9"/>
            <!-- Door window -->
            <rect x="${x+.15*v}" y="${b+4*s}"
                  width="${.7*v}" height="${.35*y}"
                  rx="${1.5*s}" fill="url(#windowGlow)" opacity="0.6"/>
            <!-- Door knob -->
            <circle cx="${x+.75*v}" cy="${b+.62*y}" r="${1.5*s}"
                    fill="#FCD170" opacity="0.8"/>

            <!-- Wall corner highlights -->
            <line x1="${o+2*s}" y1="${n+4*s}" x2="${o+2*s}" y2="${n+a-2*s}"
                  stroke="rgba(255,255,255,0.06)" stroke-width="${1.5*s}"/>
        `}_illustrationGrid(t,e,i){const s=i/50,r=72*s,a=4*s,o=e-r/2+4*s,n=o+.22*r,l=o+.42*r,c=44*s,d=32*s,p=3*s;return j`
            <!-- Outer glow halo -->
            <circle cx="${t}" cy="${e}" r="${i+4}" fill="none"
                    stroke="#488fc2" stroke-width="1.2" opacity="0.25"/>

            <!-- Main pole (tapered slightly) -->
            <polygon points="${t-a/2},${o+r}
                             ${t+a/2},${o+r}
                             ${t+.35*a},${o}
                             ${t-.35*a},${o}"
                     fill="url(#poleGrad)" stroke="#5c7a9b" stroke-width="${1*s}"/>

            <!-- Ground footing -->
            <rect x="${t-8*s}" y="${o+r-4*s}"
                  width="${16*s}" height="${4*s}" rx="${2*s}"
                  fill="#5c7a9b" opacity="0.6"/>

            <!-- Upper cross-arm -->
            <rect x="${t-c/2}" y="${n-3*s}" width="${c}" height="${5*s}"
                  rx="${2*s}" fill="url(#poleGrad)" stroke="#5c7a9b" stroke-width="${.8*s}"/>
            <!-- Upper arm support brace -->
            <line x1="${t}" y1="${n+2*s}"
                  x2="${t-.4*c}" y2="${n+14*s}"
                  stroke="#5c7a9b" stroke-width="${2*s}" opacity="0.5"/>
            <line x1="${t}" y1="${n+2*s}"
                  x2="${t+.4*c}" y2="${n+14*s}"
                  stroke="#5c7a9b" stroke-width="${2*s}" opacity="0.5"/>

            <!-- Lower cross-arm -->
            <rect x="${t-d/2}" y="${l-3*s}" width="${d}" height="${5*s}"
                  rx="${2*s}" fill="url(#poleGrad)" stroke="#5c7a9b" stroke-width="${.8*s}"/>

            <!-- Insulators — upper arm (2 sides) -->
            <circle cx="${t-c/2}" cy="${n}" r="${p}"
                    fill="#838bc5" stroke="#488fc2" stroke-width="${1*s}"/>
            <circle cx="${t+c/2}" cy="${n}" r="${p}"
                    fill="#838bc5" stroke="#488fc2" stroke-width="${1*s}"/>
            <!-- Insulators — lower arm -->
            <circle cx="${t-d/2}" cy="${l}" r="${p}"
                    fill="#838bc5" stroke="#488fc2" stroke-width="${1*s}"/>
            <circle cx="${t+d/2}" cy="${l}" r="${p}"
                    fill="#838bc5" stroke="#488fc2" stroke-width="${1*s}"/>

            <!-- Power line cables drooping from upper arm -->
            <path d="M${t-c/2},${n}
                     Q${t-.7*c},${n+18*s} ${t-.95*c-15*s},${n+12*s}"
                  fill="none" stroke="#488fc2" stroke-width="${1.5*s}" opacity="0.6"/>
            <path d="M${t+c/2},${n}
                     Q${t+.7*c},${n+18*s} ${t+.95*c+15*s},${n+12*s}"
                  fill="none" stroke="#488fc2" stroke-width="${1.5*s}" opacity="0.6"/>

            <!-- Lower wire cables -->
            <path d="M${t-d/2},${l}
                     Q${t-.65*d},${l+14*s} ${t-.9*d-12*s},${l+9*s}"
                  fill="none" stroke="#488fc2" stroke-width="${1.2*s}" opacity="0.5"/>
            <path d="M${t+d/2},${l}
                     Q${t+.65*d},${l+14*s} ${t+.9*d+12*s},${l+9*s}"
                  fill="none" stroke="#488fc2" stroke-width="${1.2*s}" opacity="0.5"/>

            <!-- Lightning bolt accent (center, decorative) -->
            <path d="M${t-3*s},${l+8*s} L${t-5*s},${l+14*s}
                     L${t},${l+14*s} L${t},${l+20*s}
                     L${t+4*s},${l+11*s} L${t},${l+11*s} Z"
                  fill="#FCD170" opacity="0.6"/>
        `}_illustrationEV(t,e,i){const s=i/44,r=22*s,a=36*s,o=t-28*s,n=e-a/2,l=e+4*s,c=52*s,d=22*s,p=t+18*s-c/2,h=6*s;return j`
            <!-- Outer glow halo -->
            <circle cx="${t}" cy="${e}" r="${i+4}" fill="none"
                    stroke="#8DC892" stroke-width="1.2" opacity="0.25"/>

            <!-- Charger station box -->
            <rect x="${o}" y="${n}" width="${r}" height="${a}"
                  rx="${4*s}" fill="#1a2e22" stroke="#8DC892" stroke-width="${1.8*s}" opacity="0.95"/>
            <!-- Charger screen -->
            <rect x="${o+3*s}" y="${n+4*s}" width="${r-6*s}" height="${10*s}"
                  rx="${2*s}" fill="#0a1a12" stroke="#8DC892" stroke-width="${.8*s}" opacity="0.8"/>
            <!-- Screen text (power reading) -->
            <text x="${o+r/2}" y="${n+4*s+8*s}"
                  font-family="'Courier New',monospace" font-size="${5.5*s}"
                  fill="#8DC892" text-anchor="middle" opacity="0.8">AC</text>
            <!-- Charging bolt on charger -->
            <path d="M${o+r/2-3*s},${n+18*s}
                     L${o+r/2-5*s},${n+25*s}
                     L${o+r/2},${n+25*s}
                     L${o+r/2},${n+32*s}
                     L${o+r/2+4*s},${n+22*s}
                     L${o+r/2},${n+22*s} Z"
                  fill="#FCD170" opacity="0.9"/>
            <!-- Status LED -->
            <circle cx="${o+r-5*s}" cy="${n+5*s}" r="${2.2*s}"
                    fill="#8DC892" opacity="0.9">
                <animate attributeName="opacity" values="0.9;0.3;0.9" dur="1.8s" repeatCount="indefinite"/>
            </circle>
            <!-- Cable from charger to car -->
            <path d="M${o+r},${n+.55*a}
                     C${o+r+10*s},${n+.55*a}
                       ${p-10*s},${l}
                       ${p},${l}"
                  fill="none" stroke="#8DC892" stroke-width="${2.5*s}"
                  stroke-linecap="round" opacity="0.7"/>
            <!-- Cable connector plug at car -->
            <circle cx="${p}" cy="${l}" r="${3*s}"
                    fill="#8DC892" opacity="0.85"/>

            <!-- Car body — sedan profile -->
            <!-- Underbody -->
            <rect x="${p+5*s}" y="${l}" width="${c-10*s}" height="${d/2}"
                  rx="${3*s}" fill="url(#carGrad)" stroke="#8DC892" stroke-width="${1.5*s}"/>
            <!-- Cabin (roofline) -->
            <path d="M${p+12*s},${l}
                     L${p+10*s},${l-.7*d}
                     L${p+20*s},${l-.85*d}
                     L${p+c-18*s},${l-.85*d}
                     L${p+c-10*s},${l-.7*d}
                     L${p+c-8*s},${l} Z"
                  fill="url(#carGrad)" stroke="#8DC892" stroke-width="${1.5*s}"/>
            <!-- Windshield -->
            <path d="M${p+13*s},${l-2*s}
                     L${p+11*s},${l-.62*d}
                     L${p+22*s},${l-.78*d}
                     L${p+24*s},${l-2*s} Z"
                  fill="rgba(100,200,200,0.22)" stroke="rgba(100,200,200,0.4)" stroke-width="${.8*s}"/>
            <!-- Rear window -->
            <path d="M${p+c-14*s},${l-2*s}
                     L${p+c-22*s},${l-2*s}
                     L${p+c-20*s},${l-.78*d}
                     L${p+c-12*s},${l-.62*d} Z"
                  fill="rgba(100,200,200,0.22)" stroke="rgba(100,200,200,0.4)" stroke-width="${.8*s}"/>
            <!-- Wheels -->
            <circle cx="${p+14*s}" cy="${l+d/2-1*s}" r="${h}"
                    fill="#1a2525" stroke="#8DC892" stroke-width="${2*s}"/>
            <circle cx="${p+14*s}" cy="${l+d/2-1*s}" r="${.4*h}"
                    fill="#8DC892" opacity="0.5"/>
            <circle cx="${p+c-14*s}" cy="${l+d/2-1*s}" r="${h}"
                    fill="#1a2525" stroke="#8DC892" stroke-width="${2*s}"/>
            <circle cx="${p+c-14*s}" cy="${l+d/2-1*s}" r="${.4*h}"
                    fill="#8DC892" opacity="0.5"/>
            <!-- Headlight -->
            <ellipse cx="${p+c-7*s}" cy="${l+d/2-6*s}"
                     rx="${4*s}" ry="${2.5*s}"
                     fill="#FFF9C4" opacity="0.6"/>
        `}_updateFlowsImperative(){if(!this._hass)return;const t=this._getState("solar_power"),e=this._getState("battery_power"),i=this._getState("grid_import_power"),s=this._getState("grid_export_power"),r=this._getState("ev_power"),a=this._getState("battery_soc"),o=Math.max(0,e),n=Math.max(0,-e),l=Math.max(0,t+i+n-s-o-r),c={solar:t,battery:e,gridImport:i,gridExport:s,home:l,ev:r,soc:a},d=JSON.stringify(c);if(this._lastKey===d)return;this._lastKey=d;const p=[];for(const t of["solar_power","battery_power","grid_import_power","grid_export_power","ev_power","battery_soc"]){const e=this._hass.states[`${this.entityPrefix}${t}`];e&&"unavailable"!==e.state&&"unknown"!==e.state||p.push(t)}const h=this.renderRoot.getElementById("entity-status");h&&(p.length>0?(h.textContent=`⚠ ${p.length} ${this._t("sensor_unavailable")}`,h.style.display="block"):h.style.display="none"),this._animateValue("val-solar",t),this._animateValue("val-batt-power",Math.abs(e),800,t=>o>10?`↑ ${ht(t)}`:n>10?`↓ ${ht(t)}`:ht(t)),this._animateValue("val-home",l),this._animateValue("val-ev",r),this._setText("val-solar-kwh",`${this._t("today")} ${this._getStateStr("daily_solar_energy")} kWh`);const _=this._getState("forecast_corrected_today");this._setText("val-solar-forecast",_>0?`☀ ${_.toFixed(0)} kWh ${this._t("forecast")||"Forecast"}`:""),this._setText("val-ev-kwh",`${this._t("today")} ${this._getStateStr("daily_ev_energy")} kWh`),this._setText("val-home-kwh",`${this._t("today")} ${this._getState("daily_home_energy").toFixed(1)} kWh`);const g=this._getState("daily_battery_charge_energy"),u=this._getState("daily_battery_discharge_energy");this._setText("val-batt-kwh",`+${g.toFixed(1)} / -${u.toFixed(1)} kWh`);const f=this._getState("daily_grid_import_energy"),m=this._getState("daily_grid_export_energy");this._setText("val-grid-kwh",`↓${f.toFixed(1)} / ↑${m.toFixed(1)} kWh`);const v=this.renderRoot.getElementById("val-grid-single");s>10?(this._animateValue("val-grid-single",s,800,t=>`↑ ${ht(t)}`),v&&v.setAttribute("fill","#8353d1")):i>10?(this._animateValue("val-grid-single",i,800,t=>`↓ ${ht(t)}`),v&&v.setAttribute("fill","#488fc2")):(this._animateValue("val-grid-single",0),v&&v.setAttribute("fill","#488fc2"));const y=this._getState("battery_temperature");this._setText("val-inv-temp",y>0?`${y.toFixed(0)}°C`:"");const x=this._getStateStr("charging_state"),b=this._compact?22:30;this._setText("val-inv-status",x.length>b?x.substring(0,b-1)+"…":x),this._updateBatterySOC(a,o,n);const $=this.renderRoot.getElementById("label-grid");$&&($.textContent=this._t("grid"),$.setAttribute("fill",s>i?"#8353d1":"#488fc2"));const w=this.renderRoot.getElementById("label-grid-state");w&&(s>10&&s>i?(w.textContent=this._t("exporting"),w.setAttribute("fill","#8353d1")):i>10?(w.textContent=this._t("importing"),w.setAttribute("fill","#488fc2")):w.textContent="");const k=this.renderRoot.getElementById("label-batt-state"),S=this.renderRoot.getElementById("val-batt-power"),C=o>10?"#f06292":"#4db6ac";k&&(o>10?(k.textContent=this._t("charging"),k.setAttribute("fill","#f06292")):n>10?(k.textContent=this._t("discharging"),k.setAttribute("fill","#4db6ac")):k.textContent=""),S&&S.setAttribute("fill",C);const E=this.renderRoot.getElementById("label-ev-state");if(E){const t=this._hass?.states["binary_sensor.sem_ev_connected"],e=this._hass?.states["binary_sensor.sem_ev_charging"],i=t&&"on"===t.state;e&&"on"===e.state||r>10?(E.textContent=this._t("charging"),E.setAttribute("fill","#8DC892")):i?(E.textContent=this._t("connected")||"Verbunden",E.setAttribute("fill","rgba(141,200,146,0.6)")):E.textContent=""}this._updateSunPosition(t),this._updateFlow("flow-solar",t>10,!1,_t(t));const z=this.renderRoot.getElementById("flow-battery");z&&(z.dataset.color=o>10?"#f06292":"#4db6ac"),this._updateFlow("flow-battery",Math.abs(e)>10,e<0,_t(e));const M=this.renderRoot.getElementById("flow-grid");M&&(M.dataset.color=s>i?"#8353d1":"#488fc2"),this._updateFlow("flow-grid",i>10||s>10,i>s,_t(i||s)),this._updateFlow("flow-home",l>10,!1,_t(l)),this._updateFlow("flow-ev",r>10,!1,_t(r)),this._compact||this._updateDeviceLabels()}_updateBatterySOC(t,e,i){const s=this._getLayout(),r=s.B.r/50,a=64*r,o=a-12*r,n=s.B.cy-a/2+8*r,l=Math.max(0,Math.min(o,o*(t/100))),c=n+o-l,d=this.renderRoot.getElementById("batt-fill");d&&(d.setAttribute("height",l.toFixed(1)),d.setAttribute("y",c.toFixed(1)),e>10?d.setAttribute("fill","#f06292"):d.setAttribute("fill","url(#battFillGrad)")),this._setText("batt-soc-text",`${t.toFixed(0)}%`);const p=this.renderRoot.getElementById("batt-bolt");p&&(p.style.display=e>10?"":"none")}_updateSunPosition(t){const e=this._hass?.states["sun.sun"],i=(e&&parseFloat(e.attributes?.elevation)||-90)<0,s=this.renderRoot.getElementById("moon-crescent"),r=this.renderRoot.getElementById("stars"),a=this.renderRoot.getElementById("sun-glow");s&&(s.style.display=i?"block":"none"),r&&(r.style.display=i?"block":"none"),a&&(a.style.opacity=i?"0.3":"0.9");const o=this.renderRoot.getElementById("sun-spark");o&&(o.style.opacity=t>50?String(Math.min(1,.3+t/5e3)):"0"),this._setText("sun-power-label",t>10?ht(t):"");const n=e?.attributes;if(n){if(n.next_rising){const t=new Date(n.next_rising);this._setText("sun-rising",`${t.getHours().toString().padStart(2,"0")}:${t.getMinutes().toString().padStart(2,"0")}`)}if(n.next_setting){const t=new Date(n.next_setting);this._setText("sun-setting",`${t.getHours().toString().padStart(2,"0")}:${t.getMinutes().toString().padStart(2,"0")}`)}const e=n.next_rising?new Date(n.next_rising).getTime():0,r=n.next_setting?new Date(n.next_setting).getTime():0,o=Date.now();let l=.5;if(!i&&e&&r){const t=e-864e5,i=r-t;i>0&&(l=(o-t)/i)}else l=e&&o<e?0:1;l=Math.max(.06,Math.min(.94,l));const c=this._getLayout(),d=this.renderRoot.querySelector("#sun-arc-path");if(d)try{const e=d.getTotalLength(),r=d.getPointAtLength(l*e),o=r.x-c.sunX,n=r.y-c.sunY,p=i?.7:.7+.6*Math.min(1,t/1e4);a&&a.setAttribute("transform",`translate(${o.toFixed(1)},${n.toFixed(1)}) translate(${c.sunX},${c.sunY}) scale(${p.toFixed(2)}) translate(${(-c.sunX).toFixed(1)},${(-c.sunY).toFixed(1)})`),s&&i&&s.setAttribute("transform",`translate(${o.toFixed(1)},${n.toFixed(1)})`);const h=this.renderRoot.getElementById("sun-power-label");h&&(h.setAttribute("x",r.x.toFixed(1)),h.setAttribute("y",(r.y+c.sunR*p+16).toFixed(1)));const _=this.renderRoot.getElementById("sun-spark");if(t>50&&_){const e=r.x,i=r.y,s=c.S.cx,a=c.S.cy-c.S.r,o=s-e,n=a-i,l=Math.sqrt(o*o+n*n),d=Math.max(2,Math.round(l/30)),p=6+Math.min(8,t/1e3),h=Math.atan2(n,o),g=-Math.sin(h),u=Math.cos(h),f=8*d;let m=`M${e.toFixed(1)},${i.toFixed(1)}`;for(let t=1;t<=f;t++){const s=t/f,r=e+o*s,a=i+n*s,l=Math.sin(s*d*Math.PI*2)*p;m+=` L${(r+g*l).toFixed(1)},${(a+u*l).toFixed(1)}`}const v=12-7*Math.min(1,t/1e4),y=`${v.toFixed(0)}:${e.toFixed(0)}`;if(_.dataset.sig!==y){_.dataset.sig=y;const e=3+Math.floor(Math.min(3,t/3e3));let i=`\n                                <path id="spark-wave" d="${m}" fill="none"\n                                      stroke="rgba(255,200,60,0.12)" stroke-width="2.5" stroke-linecap="round"\n                                      filter="url(#glowSun)"/>`;for(let t=0;t<e;t++){const e=(v*(.7+.6*Math.random())).toFixed(1),s=(Math.random()*v).toFixed(1),r=1.5+2*Math.random(),a=(.4+.5*Math.random()).toFixed(2);i+=t%2==0?`\n                                        <circle r="${r.toFixed(1)}" fill="rgba(255,220,60,${a})" filter="url(#glowSun)">\n                                            <animateMotion dur="${e}s" repeatCount="indefinite" calcMode="paced" begin="-${s}s">\n                                                <mpath href="#spark-wave"/></animateMotion>\n                                        </circle>`:`\n                                        <circle r="${(.6*r).toFixed(1)}" fill="rgba(255,255,230,${a})">\n                                            <animateMotion dur="${e}s" repeatCount="indefinite" calcMode="paced" begin="-${s}s">\n                                                <mpath href="#spark-wave"/></animateMotion>\n                                        </circle>`}_.innerHTML=i}}}catch(t){}}}_updateFlow(t,e,i,s){const r=this.renderRoot.getElementById(t);if(!r)return;if(r.style.opacity=e?"1":"0",!e)return void(r.dataset.sig="");const a=r.dataset.pathId,o=r.dataset.pathD,n=r.dataset.color,l=parseInt(r.dataset.count,10)||2,c=`${i?"r":"f"}:${s.toFixed(1)}:${n}:${o}`;r.dataset.sig!==c&&(r.dataset.sig=c,r.innerHTML=this._flowEffects(o,a,n,l,s,i))}_flowEffects(t,e,i,s,r,a){const o=r.toFixed(1),n=String(a?28:-28),l=a?' keyPoints="1;0" keyTimes="0;1"':"";let c=`<path d="${t}" fill="none" stroke="${i}" stroke-width="5"\n                           stroke-dasharray="8,20" opacity="0.2" stroke-linecap="round">\n                        <animate attributeName="stroke-dashoffset" from="0" to="${n}"\n                                 dur="${o}s" repeatCount="indefinite"/>\n                      </path>`;c+=`<path d="${t}" fill="none" stroke="rgba(255,255,255,0.5)" stroke-width="1.2"\n                         stroke-dasharray="6,22" opacity="0.45" stroke-linecap="round">\n                     <animate attributeName="stroke-dashoffset" from="0" to="${n}"\n                              dur="${o}s" repeatCount="indefinite"/>\n                   </path>`,c+=`<path d="${t}" fill="none" stroke="${i}" stroke-width="2.5"\n                         stroke-dasharray="8,20" opacity="0.65" stroke-linecap="round">\n                     <animate attributeName="stroke-dashoffset" from="0" to="${n}"\n                              dur="${o}s" repeatCount="indefinite"/>\n                   </path>`;for(let t=0;t<s;t++){const a=t/s*r;c+=`\n                <circle r="5" fill="${i}" opacity="0.12">\n                    <animateMotion dur="${o}s" repeatCount="indefinite" calcMode="paced"${l} begin="-${a.toFixed(2)}s">\n                        <mpath href="#${e}"/>\n                    </animateMotion>\n                </circle>\n                <circle r="2.5" fill="${i}" opacity="0.95">\n                    <animateMotion dur="${o}s" repeatCount="indefinite" calcMode="paced"${l} begin="-${a.toFixed(2)}s">\n                        <mpath href="#${e}"/>\n                    </animateMotion>\n                </circle>\n                <circle r="1" fill="rgba(255,255,255,0.9)" opacity="0.85">\n                    <animateMotion dur="${o}s" repeatCount="indefinite" calcMode="paced"${l} begin="-${a.toFixed(2)}s">\n                        <mpath href="#${e}"/>\n                    </animateMotion>\n                </circle>`}return c}_updateDeviceLabels(){const t=this.renderRoot.getElementById("device-labels");if(!t)return;const e=this._hass.states[`${this.entityPrefix}controllable_devices_count`];if(!e?.attributes?.devices)return void(t.innerHTML="");const i=Object.entries(e.attributes.devices).filter(([,t])=>"ev_charger"!==t.device_type).map(([t,e])=>{const i=e.power_entity?this._hass.states[e.power_entity]:null,s=i?parseFloat(i.state)||0:e.current_power||0;return{id:t,...e,power:s}}).sort((t,e)=>e.power-t.power).slice(0,3);if(!i.length)return void(t.innerHTML="");const s="'Segoe UI','Roboto',sans-serif",r=this._getLayout().H,a=pt;let o="";i.forEach((t,e)=>{let i=(t.name||t.id).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");i.length>22&&(i=i.substring(0,21)+"…");const n=a[e%a.length],l=t.is_on||t.power>5,c=310+50*e,d=`M${r.cx+r.r},${r.cy+10+8*e} C${r.cx+r.r+40},${r.cy+30+15*e} 510,${c-10} 524,${c}`;if(o+=`<path d="${d}" fill="none" stroke="${n}" stroke-width="1"\n                              stroke-dasharray="3,5" opacity="${l?.3:.1}"/>`,t.power>5){const i=_t(t.power).toFixed(1);o+=`<path id="dev-path-${e}" d="${d}" fill="none" stroke="none"/>\n                            <circle r="1.5" fill="${n}" opacity="0.8">\n                                <animateMotion dur="${i}s" repeatCount="indefinite" calcMode="paced">\n                                    <mpath href="#dev-path-${e}"/></animateMotion>\n                            </circle>`}o+=`<circle cx="540" cy="${c}" r="14" fill="rgba(128,128,128,${l?.06:.02})"\n                                stroke="${n}" stroke-width="0.8" opacity="${l?.7:.3}"/>`;const p=this._deviceIcon(t.device_type,t.name||t.id);o+=`<g transform="translate(540,${c}) scale(0.7)" stroke="${n}" fill="none"\n                           opacity="${l?.6:.25}" stroke-width="1.3" stroke-linecap="round">${p}</g>`,o+=`<text x="560" y="${c-2}" font-family="${s}" font-size="10"\n                              font-weight="500" fill="${n}" opacity="0.7">${i}</text>`,o+=`<text x="560" y="${c+11}" font-family="${s}" font-size="10"\n                              font-weight="700" fill="${n}" opacity="${l?.9:.4}">${ht(t.power)}</text>`}),t.innerHTML=o}_animateValue(t,e,i=800,s=null){const r=this.renderRoot.getElementById(t);if(!r)return;this._animFrames[t]&&cancelAnimationFrame(this._animFrames[t]);const a=s||(t=>ht(t)),o=this._currentValues[t]||0;if(this._currentValues[t]=e,Math.abs(o-e)<1)return void(r.textContent=a(e));const n=performance.now(),l=s=>{const c=Math.min(1,(s-n)/i),d=c<.5?2*c*c:1-Math.pow(-2*c+2,2)/2;r.textContent=a(o+(e-o)*d),c<1?this._animFrames[t]=requestAnimationFrame(l):delete this._animFrames[t]};this._animFrames[t]=requestAnimationFrame(l)}_setText(t,e){const i=this.renderRoot.getElementById(t);i&&i.textContent!==e&&(i.textContent=e)}_getState(t){if(!this._hass)return 0;const e=this._hass.states[`${this.entityPrefix}${t}`];if(!e)return 0;const i=parseFloat(e.state);return isNaN(i)?0:i}_getStateStr(t){if(!this._hass)return"";const e=this._hass.states[`${this.entityPrefix}${t}`];return e?e.state:""}_glowFilter(t,e,i){return j`<filter id="${t}" x="-35%" y="-35%" width="170%" height="170%">
            <feGaussianBlur stdDeviation="${i}" result="blur"/>
            <feFlood flood-color="${e}" flood-opacity="0.28"/>
            <feComposite in2="blur" operator="in"/>
            <feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge>
        </filter>`}_showMoreInfo(t){const e=`${this.entityPrefix}${t}`;this.dispatchEvent(new CustomEvent("hass-more-info",{bubbles:!0,composed:!0,detail:{entityId:e}}))}_getLayout(){return this._compact?{vb:"0 0 400 680",S:{cx:200,cy:100,r:44,labelY:154},I:{cx:200,cy:232,r:20},B:{cx:100,cy:360,r:44,labelY:414},G:{cx:300,cy:360,r:44,labelY:414},H:{cx:200,cy:540,r:48,labelY:598},E:{cx:84,cy:555,r:34,labelY:598},paths:{solar:"M200,144 L200,212",battery:"M188,242 C155,278 120,315 100,316",grid:"M212,242 C245,278 280,315 300,316",home:"M200,252 C200,390 200,460 200,492",ev:"M200,252 C200,400 140,490 84,521"},sunArc:"M30,68 Q200,6 370,68",sunX:200,sunY:20,sunR:12,sunRisingX:40,sunSettingX:360,sunLabelY:76,starX:[60,120,280,330,180],starY:[20,12,18,24,8],font:{label:11,value:15,sub:10},statusY:660,wmX:390,wmY:676}:{vb:"0 0 700 510",S:{cx:85,cy:140,r:48,labelY:200},I:{cx:220,cy:200,r:20},E:{cx:150,cy:390,r:42,labelY:442},B:{cx:340,cy:390,r:48,labelY:448},H:{cx:400,cy:230,r:52,labelY:292},G:{cx:570,cy:140,r:46,labelY:198},paths:{solar:"M118,148 C158,165 192,188 208,200",home:"M242,198 C300,200 350,210 360,218",battery:"M228,215 C260,280 320,340 338,342",grid:"M232,188 C320,130 450,110 524,130",ev:"M210,215 C180,275 162,330 150,348"},sunArc:"M20,52 Q330,2 640,52",sunX:330,sunY:12,sunR:12,sunRisingX:28,sunSettingX:632,sunLabelY:60,starX:[100,200,450,550,330],starY:[20,12,15,28,8],font:{label:11,value:16,sub:10},statusY:495,wmX:690,wmY:506}}_deviceIcon(t,e){const i=(e||"").toLowerCase();return"ev_charger"===(t||"").toLowerCase()||i.includes("keba")||i.includes("charger")||i.includes("wallbox")?'<rect x="-5" y="-9" width="10" height="14" rx="2"/>\n                    <path d="M-1.5,-3.5 L0,1.5 L1.5,-3.5"/>\n                    <line x1="0" y1="5" x2="0" y2="9"/>':i.includes("heiz")||i.includes("heat")||i.includes("warm")||i.includes("boiler")?'<path d="M-3,-9 C-3,-3 3,-3 3,-9"/>\n                    <path d="M-3,-2 C-3,4 3,4 3,-2"/>\n                    <path d="M-3,5 C-3,9 3,9 3,5"/>':i.includes("wash")||i.includes("spül")||i.includes("geschirr")||i.includes("wasch")?'<circle r="9"/><circle r="4.5"/><circle r="1.3" fill="currentColor" opacity="0.3" stroke="none"/>':i.includes("pool")||i.includes("pump")?'<circle r="7"/><path d="M-5,0 L5,0 M0,-5 L0,5" opacity="0.5"/>':i.includes("klima")||i.includes("ac")||i.includes("cool")||i.includes("air")?'<rect x="-9" y="-5" width="18" height="10" rx="2"/>\n                    <path d="M-5,5 C-5,9 -2,9 -2,5" fill="none"/>\n                    <path d="M2,5 C2,9 5,9 5,5" fill="none"/>':i.includes("light")||i.includes("licht")||i.includes("lamp")?'<path d="M-4,-9 C-7,-2 -2,3 -1.5,5 L1.5,5 C2,3 7,-2 4,-9 C2,-12 -2,-12 -4,-9Z"/>\n                    <line x1="-1.5" y1="6" x2="1.5" y2="6"/>':'<path d="M-2.5,-9 L-2.5,0 L-5,0 L0,9 L0,0 L2.5,0 L-2.5,-9Z"/>'}getCardSize(){return 7}static getStubConfig(){return{entity_prefix:"sensor.sem_"}}},{type:"sem-system-diagram-card",name:"SEM System Diagram",description:"Power flow visualization with inline SVG illustrations for each energy component"});let me=null;const ve=dt||{solar:"#ff9800",gridImport:"#488fc2",gridExport:"#8353d1",batteryOut:"#4db6ac",home:"#5BC8D8",ev:"#8DC892"},ye={costs:{title:"energy_costs",y_label:"_currency_",stacked:!1,daily:[{suffix:"daily_costs",name:"Import",color:ve.gridImport,type:"bar"},{suffix:"daily_export_revenue",name:"export",color:ve.gridExport,type:"bar"},{suffix:"daily_net_cost",name:"net",color:ve.solar,type:"line"}],monthly:[{suffix:"monthly_costs",name:"Import",color:ve.gridImport,type:"bar"},{suffix:"monthly_export_revenue",name:"export",color:ve.gridExport,type:"bar"},{suffix:"monthly_net_cost",name:"net",color:ve.solar,type:"line"}]},savings:{title:"energy_savings",y_label:"_currency_",stacked:!0,daily:[{suffix:"daily_savings",name:"solar_savings",color:ve.solar,type:"area"},{suffix:"daily_battery_savings",name:"battery_savings",color:ve.batteryOut,type:"area"}],monthly:[{suffix:"monthly_savings",name:"solar_savings",color:ve.solar,type:"area"},{suffix:"monthly_battery_savings",name:"battery_savings",color:ve.batteryOut,type:"area"}]},energy:{title:"energy_balance",y_label:"kWh",stacked:!1,daily:[{suffix:"daily_solar_energy",name:"solar",color:ve.solar,type:"bar"},{suffix:"daily_home_energy",name:"home",color:ve.home,type:"bar"},{suffix:"daily_grid_import_energy",name:"grid_import",color:ve.gridImport,type:"bar"},{suffix:"daily_grid_export_energy",name:"grid_export",color:ve.gridExport,type:"bar"}],monthly:[{suffix:"monthly_solar_energy",name:"solar",color:ve.solar,type:"bar"},{suffix:"monthly_home_energy",name:"home",color:ve.home,type:"bar"},{suffix:"monthly_grid_import_energy",name:"grid_import",color:ve.gridImport,type:"bar"},{suffix:"monthly_grid_export_energy",name:"grid_export",color:ve.gridExport,type:"bar"}]},power:{title:"power_flow",y_label:"W",stacked:!1,hourly:[{suffix:"solar_power",name:"solar",color:ve.solar,type:"area"},{suffix:"home_consumption_power",name:"home",color:ve.home,type:"area"},{suffix:"grid_power",name:"grid",color:ve.gridImport,type:"area"}]},battery:{title:"battery",y_label:"W",y2_label:"%",stacked:!1,hourly:[{suffix:"battery_power",name:"power",color:ve.batteryOut,type:"area"},{suffix:"battery_soc",name:"soc",color:"#ff9800",type:"line",y_axis:1}]},ev:{title:"ev_charging",y_label:"W",stacked:!0,defaultPeriod:"today",hourly:[{suffix:"flow_solar_to_ev_power",name:"solar",color:ve.solar,type:"area"},{suffix:"flow_battery_to_ev_power",name:"battery",color:ve.batteryOut,type:"area"},{suffix:"flow_grid_to_ev_power",name:"grid",color:ve.gridImport,type:"area"}],daily:[{suffix:"daily_ev_energy",name:"ev_energy",color:ve.ev,type:"bar"}],monthly:[{suffix:"monthly_ev_energy",name:"ev_energy",color:ve.ev,type:"bar"}]}};yt("sem-chart-card",class extends xt{constructor(){super(),this._chart=null,this._period=null,this._fetchTimer=null,this._cachedChartTheme=null,this._boundPeriodHandler=t=>this._onPeriodChange(t.detail),this._prefix="sensor.sem_",this._preset=null}setConfig(t){if(!t.preset&&!t.series)throw new Error("sem-chart-card requires either preset or series config");this._config=t,this._prefix=t.entity_prefix||"sensor.sem_",this._preset=t.preset?ye[t.preset]:null,this.requestUpdate()}set hass(t){this._hass=t;const e=t?.language;if(e!==this._lang)return this._lang=e,void this.requestUpdate();this._period||this._setDefaultPeriod()}get hass(){return this._hass}connectedCallback(){super.connectedCallback(),document.addEventListener("sem-period-change",this._boundPeriodHandler)}disconnectedCallback(){super.disconnectedCallback(),document.removeEventListener("sem-period-change",this._boundPeriodHandler),this._chart&&(this._chart.destroy(),this._chart=null),clearTimeout(this._fetchTimer)}firstUpdated(){this._period||this._setDefaultPeriod()}static get styles(){return a`
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
        `}render(){const t=this._preset||{},e=this._config?.title?this._t(this._config.title):this._t(t.title||"SEM Chart"),i=this._period?.labelKey?this._t(this._period.labelKey):"";return W`
            <ha-card>
                <div class="sem-chart-wrap">
                    <div class="chart-header">
                        <div class="chart-title">${e}</div>
                        <div class="chart-subtitle">${i}</div>
                    </div>
                    <div class="chart-container">
                        <canvas></canvas>
                        <div class="empty-msg">${this._t("loading")}</div>
                    </div>
                </div>
            </ha-card>
        `}_startOfDayInHaTz(t){return function(t,e){if(!e)return new Date(t.getFullYear(),t.getMonth(),t.getDate());try{const i=new Intl.DateTimeFormat("en-US",{timeZone:e,year:"numeric",month:"2-digit",day:"2-digit"}),s=Object.fromEntries(i.formatToParts(t).map(t=>[t.type,t.value])),r=new Date(Number(s.year),Number(s.month)-1,Number(s.day),0,0,0,0),a=new Intl.DateTimeFormat("en-US",{timeZone:e,hour:"2-digit",minute:"2-digit",hour12:!1}).formatToParts(r),o=Number(a.find(t=>"hour"===t.type).value),n=Number(a.find(t=>"minute"===t.type).value),l=(60*o+n)%1440,c=0===l?0:l<=720?-l:1440-l;return new Date(r.getTime()+60*c*1e3)}catch(e){return new Date(t.getFullYear(),t.getMonth(),t.getDate())}}(t,this._hass?.config?.time_zone)}_setDefaultPeriod(){const t=new Date,e=this._preset,i=e&&"today"===e.defaultPeriod;if(e&&(i||"24h"===e.defaultPeriod||e.hourly&&!e.daily)){const e=i?this._startOfDayInHaTz(t):new Date(t.getTime()-864e5),s=i?"period_today":"last_24h",r=i?"today":"24h";this._onPeriodChange({start:e,end:t,granularity:"hour",labelKey:s,key:r})}else{const e=t.getDay()||7,i=this._startOfDayInHaTz(t);i.setDate(i.getDate()-(e-1)),this._onPeriodChange({start:i,end:t,granularity:"day",labelKey:"period_this_week",key:"week"})}}_onPeriodChange(t){this._period={...t,labelKey:t.labelKey||{today:"period_today",yesterday:"period_yesterday",week:"period_this_week",month:"period_this_month",year:"period_this_year","24h":"last_24h"}[t.key]},this.requestUpdate(),clearTimeout(this._fetchTimer),this._fetchTimer=setTimeout(()=>this._fetchAndRender(),150)}_resolveSeries(){if(this._config?.series)return this._config.series.map(t=>({entity:t.entity,name:t.name||t.entity,color:t.color||"#42A5F5",type:t.type||"bar",y_axis:t.y_axis||0}));const t=this._preset;if(!t)return[];const e=this._period?.granularity||"day";if(this._config?.per_charger&&"ev"===this._config?.preset&&"hour"===e)return this._discoverPerChargerSeries();return("hour"===e&&t.hourly?t.hourly:"month"===e&&t.monthly?t.monthly:t.daily||t.hourly||[]).map(t=>({entity:`${this._prefix}${t.suffix}`,name:this._t(t.name),color:t.color,type:t.type,y_axis:t.y_axis||0}))}_discoverPerChargerSeries(){const t=this._hass?.states||{},e=["#8DC892","#64B5F6","#FFB74D","#BA68C8","#4DB6AC","#F06292","#A1887F","#7986CB"],i=/^sensor\.sem_charger_(.+)_power$/,s=[];for(const e of Object.keys(t)){const r=e.match(i);if(!r)continue;const a=r[1],o=t[e]?.attributes?.friendly_name?.replace(/^SEM\s+/i,"").replace(/\s+Power$/i,"")||a.replace(/_/g," ");s.push({id:a,eid:e,friendly:o})}return s.sort((t,e)=>t.id.localeCompare(e.id)),s.map((t,i)=>({entity:t.eid,name:t.friendly,color:e[i%e.length],type:"area",y_axis:0}))}async _fetchAndRender(){if(!this._hass||!this._period)return;const t=this._resolveSeries();if(!t.length)return;const{start:e,end:i,granularity:s}=this._period;let r;try{r=await this._fetchStatistics(t,e.toISOString(),i.toISOString(),s)}catch(t){return console.debug("sem-chart-card: fetch error",t),void this._showEmpty(this._t("data_unavailable"))}r&&!r.every(t=>!t.data.length)?(this._hideEmpty(),await this._renderChart(r,t)):this._showEmpty(this._t("no_data_for_period"))}async _fetchStatistics(t,e,i,s){const r=t.map(t=>t.entity),a="month"===s?"month":"hour"===s?"hour":"day";let o;try{o=await this._hass.callWS({type:"recorder/statistics_during_period",start_time:e,end_time:i,statistic_ids:r,period:a,types:["state","mean","max"]})}catch{o=await this._hass.callWS({type:"history/statistics_during_period",start_time:e,end_time:i,statistic_ids:r,period:a})}return t.map(t=>({data:(o[t.entity]||[]).map(t=>({x:new Date(t.start),y:t.max??t.state??t.mean??0}))}))}async _renderChart(t,e){const i=await(me||(me=new Promise((t,e)=>{if(window.Chart)return void t(window.Chart);const i=document.createElement("script");i.src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js",i.onload=()=>{const e=document.createElement("script");e.src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js",e.onload=()=>t(window.Chart),e.onerror=()=>t(window.Chart),document.head.appendChild(e)},i.onerror=()=>e(new Error("Failed to load Chart.js")),document.head.appendChild(i)}),me)),s=this.renderRoot.querySelector("canvas");if(!s)return;const r=this._theme(),a=this._preset||{},o=this._config?.stacked??a.stacked??!1;let n=this._config?.y_label||a.y_label||"";"_currency_"===n&&(n=gt(this._hass));const l=a.y2_label||"",c=e.some(t=>1===t.y_axis),d=this._period?.granularity||"day",p=s.getContext("2d"),h=e.map((e,i)=>{const s="area"===e.type,r="bar"===e.type;return{label:e.name,data:t[i].data,backgroundColor:r?e.color+"CC":s?e.color+"30":"transparent",borderColor:e.color,borderWidth:r?0:2,fill:!!s&&(o&&i>0?"-1":"origin"),type:r?"bar":"line",tension:.4,pointRadius:0,pointHitRadius:10,pointHoverRadius:4,pointHoverBorderWidth:2,pointHoverBackgroundColor:e.color,pointHoverBorderColor:"#fff",yAxisID:1===e.y_axis?"y1":"y",order:r?2:1,borderRadius:r?4:0,barPercentage:.7}}),_="hour"===d?"hour":"month"===d?"month":"day",g={id:"crosshair",afterDraw(t){if(t.tooltip?._active?.length){const e=t.tooltip._active[0].element.x,i=t.scales.y,s=t.ctx;s.save(),s.beginPath(),s.moveTo(e,i.top),s.lineTo(e,i.bottom),s.lineWidth=1,s.strokeStyle="rgba(255,255,255,0.15)",s.stroke(),s.restore()}}},u={type:"bar",data:{datasets:h},plugins:[g,{id:"gradientFill",beforeDatasetsDraw(t){const i=t.ctx;t.data.datasets.forEach((s,r)=>{if("area"!==e[r]?.type)return;if(t.getDatasetMeta(r).hidden)return;const a=t.scales[s.yAxisID||"y"];if(!a)return;const o=i.createLinearGradient(0,a.top,0,a.bottom);o.addColorStop(0,s.borderColor+"60"),o.addColorStop(.6,s.borderColor+"18"),o.addColorStop(1,s.borderColor+"02"),s.backgroundColor=o})}}],options:{responsive:!0,maintainAspectRatio:!1,animation:{duration:300,easing:"easeOutQuart"},interaction:{mode:"index",intersect:!1},plugins:{legend:{display:!0,position:"bottom",labels:{color:r.textSec||"#9e9e9e",font:{size:11,weight:"500",family:"'Segoe UI','Roboto',sans-serif"},boxWidth:12,boxHeight:12,borderRadius:3,useBorderRadius:!0,padding:14,generateLabels:t=>i.defaults.plugins.legend.labels.generateLabels(t).map((e,i)=>{const s=t.data.datasets[i];if(!s)return e;const r=s.data[s.data.length-1],a=r?.y??0,o="y1"===s.yAxisID?"%":n||"",l=Math.abs(a),c=l>=1e3?(a/1e3).toFixed(1)+"k":l<10?a.toFixed(1):a.toFixed(0);return e.text=`${e.text}: ${c} ${o}`,e})}},tooltip:{backgroundColor:r.tooltipBg||"rgba(15,18,25,0.94)",titleColor:r.tooltipText||"#e0e0e0",titleFont:{family:"'Segoe UI','Roboto',sans-serif",weight:"600",size:12},bodyColor:r.textSec||"#b0b0b0",bodyFont:{family:"'Segoe UI','Roboto',sans-serif",size:11},borderColor:r.tooltipBorder||"rgba(255,255,255,0.08)",borderWidth:1,cornerRadius:10,padding:{top:10,bottom:10,left:14,right:14},bodySpacing:6,displayColors:!0,boxPadding:4,callbacks:{label:t=>{const e=t.parsed.y,i="y1"===t.dataset.yAxisID?"%":n,s=Math.abs(e),r=s>=1e3?(e/1e3).toFixed(1)+"k":s<10?e.toFixed(2):e.toFixed(1);return` ${t.dataset.label}: ${r} ${i}`}}}},scales:{x:{type:"time",min:this._period.start.toISOString(),max:this._period.end.toISOString(),time:{unit:_,tooltipFormat:"hour"===d?"HH:mm":"month"===d?"MMM yyyy":"dd MMM",displayFormats:{hour:"HH:mm",day:"dd MMM",month:"MMM"}},grid:{color:"rgba(255,255,255,0.02)",drawBorder:!1,drawTicks:!1},ticks:{color:r.textSec||"#757575",font:{size:10,family:"'Segoe UI','Roboto',sans-serif"},maxRotation:0,padding:6,callback:(t,e,i)=>{const s=i[e];if(!s)return t;const r=new Date(s.value);if(isNaN(r))return t;const a=this._hass?.language||"en";return"hour"===_?r.toLocaleTimeString(a,{hour:"2-digit",minute:"2-digit"}):"month"===_?r.toLocaleDateString(a,{month:"short"}):r.toLocaleDateString(a,{day:"numeric",month:"short"})}},stacked:o},y:{position:"left",grid:{color:"rgba(255,255,255,0.04)",drawBorder:!1,drawTicks:!1},ticks:{color:r.textSec||"#757575",font:{size:10,family:"'Segoe UI','Roboto',sans-serif"},padding:8,callback:t=>{const e=Math.abs(t);return e>=1e3?(t/1e3).toFixed(1)+"k":e<.01&&e>0?"":t%1==0?t:t.toFixed(1)}},title:{display:!!n,text:n,color:r.textSec||"#757575",font:{size:11,family:"'Segoe UI','Roboto',sans-serif"}},stacked:o,beginAtZero:"W"!==n}}}};c&&(u.options.scales.y1={position:"right",grid:{drawOnChartArea:!1,drawTicks:!1},ticks:{color:"#ff9800",font:{size:10},padding:8,callback:t=>t+"%"},title:{display:!!l,text:l,color:"#ff9800",font:{size:11}},min:0,max:100}),this._chart&&(this._chart.destroy(),this._chart=null),this._chart=new i(p,u)}_showEmpty(t){const e=this.renderRoot.querySelector(".empty-msg");e&&(e.textContent=t,e.classList.add("visible"));const i=this.renderRoot.querySelector("canvas");i&&(i.style.display="none")}_hideEmpty(){const t=this.renderRoot.querySelector(".empty-msg");t&&t.classList.remove("visible");const e=this.renderRoot.querySelector("canvas");e&&(e.style.display="block")}getCardSize(){return 5}static getStubConfig(){return{preset:"costs"}}},{type:"sem-chart-card",name:"SEM Chart",description:"Period-reactive chart with glassmorphism styling and built-in presets"});const xe=["switch","current","input_boolean","service"],be={switch:["switch"],current:["number","input_number"],input_boolean:["input_boolean"]};function $e(t){return String(t??"").replace(/&/g,"&amp;").replace(/"/g,"&quot;").replace(/</g,"&lt;").replace(/>/g,"&gt;")}const we="width:100%;padding:8px;margin:6px 0 12px;border-radius:6px;border:1px solid rgba(255,255,255,0.1);background:rgba(0,0,0,0.2);color:inherit;box-sizing:border-box";!function(){window.Sortable||function(t,e){"object"==typeof exports&&"undefined"!=typeof module?module.exports=e():"function"==typeof define&&define.amd?define(e):(t=t||self).Sortable=e()}(this,function(){function t(t,e){var i,s=Object.keys(t);return Object.getOwnPropertySymbols&&(i=Object.getOwnPropertySymbols(t),e&&(i=i.filter(function(e){return Object.getOwnPropertyDescriptor(t,e).enumerable})),s.push.apply(s,i)),s}function e(e){for(var i=1;i<arguments.length;i++){var s=null!=arguments[i]?arguments[i]:{};i%2?t(Object(s),!0).forEach(function(t){var i,r;i=e,t=s[r=t],r in i?Object.defineProperty(i,r,{value:t,enumerable:!0,configurable:!0,writable:!0}):i[r]=t}):Object.getOwnPropertyDescriptors?Object.defineProperties(e,Object.getOwnPropertyDescriptors(s)):t(Object(s)).forEach(function(t){Object.defineProperty(e,t,Object.getOwnPropertyDescriptor(s,t))})}return e}function i(t){return(i="function"==typeof Symbol&&"symbol"==typeof Symbol.iterator?function(t){return typeof t}:function(t){return t&&"function"==typeof Symbol&&t.constructor===Symbol&&t!==Symbol.prototype?"symbol":typeof t})(t)}function s(){return(s=Object.assign||function(t){for(var e=1;e<arguments.length;e++){var i,s=arguments[e];for(i in s)Object.prototype.hasOwnProperty.call(s,i)&&(t[i]=s[i])}return t}).apply(this,arguments)}function r(t){return function(t){if(Array.isArray(t))return a(t)}(t)||function(t){if("undefined"!=typeof Symbol&&null!=t[Symbol.iterator]||null!=t["@@iterator"])return Array.from(t)}(t)||function(t,e){if(t){if("string"==typeof t)return a(t,e);var i=Object.prototype.toString.call(t).slice(8,-1);return"Map"===(i="Object"===i&&t.constructor?t.constructor.name:i)||"Set"===i?Array.from(t):"Arguments"===i||/^(?:Ui|I)nt(?:8|16|32)(?:Clamped)?Array$/.test(i)?a(t,e):void 0}}(t)||function(){throw new TypeError("Invalid attempt to spread non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method.")}()}function a(t,e){(null==e||e>t.length)&&(e=t.length);for(var i=0,s=new Array(e);i<e;i++)s[i]=t[i];return s}function o(t){if("undefined"!=typeof window&&window.navigator)return!!navigator.userAgent.match(t)}var n=o(/(?:Trident.*rv[ :]?11\.|msie|iemobile|Windows Phone)/i),l=o(/Edge/i),c=o(/firefox/i),d=o(/safari/i)&&!o(/chrome/i)&&!o(/android/i),p=o(/iP(ad|od|hone)/i),h=o(/chrome/i)&&o(/android/i),_={capture:!1,passive:!1};function g(t,e,i){t.addEventListener(e,i,!n&&_)}function u(t,e,i){t.removeEventListener(e,i,!n&&_)}function f(t,e){if(e&&(">"===e[0]&&(e=e.substring(1)),t))try{if(t.matches)return t.matches(e);if(t.msMatchesSelector)return t.msMatchesSelector(e);if(t.webkitMatchesSelector)return t.webkitMatchesSelector(e)}catch(t){return}}function m(t){return t.host&&t!==document&&t.host.nodeType?t.host:t.parentNode}function v(t,e,i,s){if(t){i=i||document;do{if(null!=e&&(">"!==e[0]||t.parentNode===i)&&f(t,e)||s&&t===i)return t}while(t!==i&&(t=m(t)))}return null}var y,x=/\s+/g;function b(t,e,i){var s;t&&e&&(t.classList?t.classList[i?"add":"remove"](e):(s=(" "+t.className+" ").replace(x," ").replace(" "+e+" "," "),t.className=(s+(i?" "+e:"")).replace(x," ")))}function $(t,e,i){var s=t&&t.style;if(s){if(void 0===i)return document.defaultView&&document.defaultView.getComputedStyle?i=document.defaultView.getComputedStyle(t,""):t.currentStyle&&(i=t.currentStyle),void 0===e?i:i[e];s[e=e in s||-1!==e.indexOf("webkit")?e:"-webkit-"+e]=i+("string"==typeof i?"":"px")}}function w(t,e){var i="";if("string"==typeof t)i=t;else do{var s=$(t,"transform")}while(s&&"none"!==s&&(i=s+" "+i),!e&&(t=t.parentNode));var r=window.DOMMatrix||window.WebKitCSSMatrix||window.CSSMatrix||window.MSCSSMatrix;return r&&new r(i)}function k(t,e,i){if(t){var s=t.getElementsByTagName(e),r=0,a=s.length;if(i)for(;r<a;r++)i(s[r],r);return s}return[]}function S(){return document.scrollingElement||document.documentElement}function C(t,e,i,s,r){if(t.getBoundingClientRect||t===window){var a,o,l,c,d,p,h=t!==window&&t.parentNode&&t!==S()?(o=(a=t.getBoundingClientRect()).top,l=a.left,c=a.bottom,d=a.right,p=a.height,a.width):(l=o=0,c=window.innerHeight,d=window.innerWidth,p=window.innerHeight,window.innerWidth);if((e||i)&&t!==window&&(r=r||t.parentNode,!n))do{if(r&&r.getBoundingClientRect&&("none"!==$(r,"transform")||i&&"static"!==$(r,"position"))){var _=r.getBoundingClientRect();o-=_.top+parseInt($(r,"border-top-width")),l-=_.left+parseInt($(r,"border-left-width")),c=o+a.height,d=l+a.width;break}}while(r=r.parentNode);return s&&t!==window&&(s=(e=w(r||t))&&e.a,t=e&&e.d,e&&(c=(o/=t)+(p/=t),d=(l/=s)+(h/=s))),{top:o,left:l,bottom:c,right:d,width:h,height:p}}}function E(t,e,i){for(var s=I(t,!0),r=C(t)[e];s;){if(!(C(s)[i]<=r))return s;if(s===S())break;s=I(s,!1)}return!1}function z(t,e,i,s){for(var r=0,a=0,o=t.children;a<o.length;){if("none"!==o[a].style.display&&o[a]!==Bt.ghost&&(s||o[a]!==Bt.dragged)&&v(o[a],i.draggable,t,!1)){if(r===e)return o[a];r++}a++}return null}function M(t,e){for(var i=t.lastElementChild;i&&(i===Bt.ghost||"none"===$(i,"display")||e&&!f(i,e));)i=i.previousElementSibling;return i||null}function D(t,e){var i=0;if(!t||!t.parentNode)return-1;for(;t=t.previousElementSibling;)"TEMPLATE"===t.nodeName.toUpperCase()||t===Bt.clone||e&&!f(t,e)||i++;return i}function F(t){var e=0,i=0,s=S();if(t)do{var r=(a=w(t)).a,a=a.d}while(e+=t.scrollLeft*r,i+=t.scrollTop*a,t!==s&&(t=t.parentNode));return[e,i]}function I(t,e){if(!t||!t.getBoundingClientRect)return S();var i=t,s=!1;do{if(i.clientWidth<i.scrollWidth||i.clientHeight<i.scrollHeight){var r=$(i);if(i.clientWidth<i.scrollWidth&&("auto"==r.overflowX||"scroll"==r.overflowX)||i.clientHeight<i.scrollHeight&&("auto"==r.overflowY||"scroll"==r.overflowY)){if(!i.getBoundingClientRect||i===document.body)return S();if(s||e)return i;s=!0}}}while(i=i.parentNode);return S()}function T(t,e){return Math.round(t.top)===Math.round(e.top)&&Math.round(t.left)===Math.round(e.left)&&Math.round(t.height)===Math.round(e.height)&&Math.round(t.width)===Math.round(e.width)}function A(t,e){return function(){var i;y||(1===(i=arguments).length?t.call(this,i[0]):t.apply(this,i),y=setTimeout(function(){y=void 0},e))}}function N(t,e,i){t.scrollLeft+=e,t.scrollTop+=i}function R(t){var e=window.Polymer,i=window.jQuery||window.Zepto;return e&&e.dom?e.dom(t).cloneNode(!0):i?i(t).clone(!0)[0]:t.cloneNode(!0)}function O(t,e){$(t,"position","absolute"),$(t,"top",e.top),$(t,"left",e.left),$(t,"width",e.width),$(t,"height",e.height)}function B(t){$(t,"position",""),$(t,"top",""),$(t,"left",""),$(t,"width",""),$(t,"height","")}function P(t,e,i){var s={};return Array.from(t.children).forEach(function(r){var a;v(r,e.draggable,t,!1)&&!r.animated&&r!==i&&(a=C(r),s.left=Math.min(null!==(r=s.left)&&void 0!==r?r:1/0,a.left),s.top=Math.min(null!==(r=s.top)&&void 0!==r?r:1/0,a.top),s.right=Math.max(null!==(r=s.right)&&void 0!==r?r:-1/0,a.right),s.bottom=Math.max(null!==(r=s.bottom)&&void 0!==r?r:-1/0,a.bottom))}),s.width=s.right-s.left,s.height=s.bottom-s.top,s.x=s.left,s.y=s.top,s}var L="Sortable"+(new Date).getTime();var H=[],U={initializeByDefault:!0},W={mount:function(t){for(var e in U)!U.hasOwnProperty(e)||e in t||(t[e]=U[e]);H.forEach(function(e){if(e.pluginName===t.pluginName)throw"Sortable: Cannot mount plugin ".concat(t.pluginName," more than once")}),H.push(t)},pluginEvent:function(t,i,s){var r=this;this.eventCanceled=!1,s.cancel=function(){r.eventCanceled=!0};var a=t+"Global";H.forEach(function(r){i[r.pluginName]&&(i[r.pluginName][a]&&i[r.pluginName][a](e({sortable:i},s)),i.options[r.pluginName]&&i[r.pluginName][t]&&i[r.pluginName][t](e({sortable:i},s)))})},initializePlugins:function(t,e,i,r){for(var a in H.forEach(function(r){var a=r.pluginName;(t.options[a]||r.initializeByDefault)&&((r=new r(t,e,t.options)).sortable=t,r.options=t.options,t[a]=r,s(i,r.defaults))}),t.options){var o;t.options.hasOwnProperty(a)&&void 0!==(o=this.modifyOption(t,a,t.options[a]))&&(t.options[a]=o)}},getEventProperties:function(t,e){var i={};return H.forEach(function(r){"function"==typeof r.eventProperties&&s(i,r.eventProperties.call(e[r.pluginName],t))}),i},modifyOption:function(t,e,i){var s;return H.forEach(function(r){t[r.pluginName]&&r.optionListeners&&"function"==typeof r.optionListeners[e]&&(s=r.optionListeners[e].call(t[r.pluginName],i))}),s}};function j(t){var i=t.sortable,s=t.rootEl,r=t.name,a=t.targetEl,o=t.cloneEl,c=t.toEl,d=t.fromEl,p=t.oldIndex,h=t.newIndex,_=t.oldDraggableIndex,g=t.newDraggableIndex,u=t.originalEvent,f=t.putSortable,m=t.extraEventProperties;if(i=i||s&&s[L]){var v,y=i.options;t="on"+r.charAt(0).toUpperCase()+r.substr(1);!window.CustomEvent||n||l?(v=document.createEvent("Event")).initEvent(r,!0,!0):v=new CustomEvent(r,{bubbles:!0,cancelable:!0}),v.to=c||s,v.from=d||s,v.item=a||s,v.clone=o,v.oldIndex=p,v.newIndex=h,v.oldDraggableIndex=_,v.newDraggableIndex=g,v.originalEvent=u,v.pullMode=f?f.lastPutMode:void 0;var x,b=e(e({},m),W.getEventProperties(r,i));for(x in b)v[x]=b[x];s&&s.dispatchEvent(v),y[t]&&y[t].call(i,v)}}function G(t,i){var s=(r=2<arguments.length&&void 0!==arguments[2]?arguments[2]:{}).evt,r=function(t,e){if(null==t)return{};var i,s=function(t,e){if(null==t)return{};for(var i,s={},r=Object.keys(t),a=0;a<r.length;a++)i=r[a],0<=e.indexOf(i)||(s[i]=t[i]);return s}(t,e);if(Object.getOwnPropertySymbols)for(var r=Object.getOwnPropertySymbols(t),a=0;a<r.length;a++)i=r[a],0<=e.indexOf(i)||Object.prototype.propertyIsEnumerable.call(t,i)&&(s[i]=t[i]);return s}(r,K);W.pluginEvent.bind(Bt)(t,i,e({dragEl:q,parentEl:Y,ghostEl:X,rootEl:Z,nextEl:J,lastDownEl:Q,cloneEl:tt,cloneHidden:et,dragStarted:gt,putSortable:nt,activeSortable:Bt.active,originalEvent:s,oldIndex:it,oldDraggableIndex:rt,newIndex:st,newDraggableIndex:at,hideGhostForTarget:At,unhideGhostForTarget:Nt,cloneNowHidden:function(){et=!0},cloneNowShown:function(){et=!1},dispatchSortableEvent:function(t){V({sortable:i,name:t,originalEvent:s})}},r))}var K=["evt"];function V(t){j(e({putSortable:nt,cloneEl:tt,targetEl:q,rootEl:Z,oldIndex:it,oldDraggableIndex:rt,newIndex:st,newDraggableIndex:at},t))}var q,Y,X,Z,J,Q,tt,et,it,st,rt,at,ot,nt,lt,ct,dt,pt,ht,_t,gt,ut,ft,mt,vt,yt=!1,xt=!1,bt=[],$t=!1,wt=!1,kt=[],St=!1,Ct=[],Et="undefined"!=typeof document,zt=p,Mt=l||n?"cssFloat":"float",Dt=Et&&!h&&!p&&"draggable"in document.createElement("div"),Ft=function(){if(Et){if(n)return!1;var t=document.createElement("x");return t.style.cssText="pointer-events:auto","auto"===t.style.pointerEvents}}(),It=function(t,e){var i=$(t),s=parseInt(i.width)-parseInt(i.paddingLeft)-parseInt(i.paddingRight)-parseInt(i.borderLeftWidth)-parseInt(i.borderRightWidth),r=z(t,0,e),a=z(t,1,e),o=r&&$(r),n=a&&$(a),l=o&&parseInt(o.marginLeft)+parseInt(o.marginRight)+C(r).width;t=n&&parseInt(n.marginLeft)+parseInt(n.marginRight)+C(a).width;return"flex"===i.display?"column"===i.flexDirection||"column-reverse"===i.flexDirection?"vertical":"horizontal":"grid"===i.display?i.gridTemplateColumns.split(" ").length<=1?"vertical":"horizontal":r&&o.float&&"none"!==o.float?(e="left"===o.float?"left":"right",!a||"both"!==n.clear&&n.clear!==e?"horizontal":"vertical"):r&&("block"===o.display||"flex"===o.display||"table"===o.display||"grid"===o.display||s<=l&&"none"===i[Mt]||a&&"none"===i[Mt]&&s<l+t)?"vertical":"horizontal"},Tt=function(t){function e(t,i){return function(s,r,a,o){var n=s.options.group.name&&r.options.group.name&&s.options.group.name===r.options.group.name;return!(null!=t||!i&&!n)||null!=t&&!1!==t&&(i&&"clone"===t?t:"function"==typeof t?e(t(s,r,a,o),i)(s,r,a,o):(r=(i?s:r).options.group.name,!0===t||"string"==typeof t&&t===r||t.join&&-1<t.indexOf(r)))}}var s={},r=t.group;r&&"object"==i(r)||(r={name:r}),s.name=r.name,s.checkPull=e(r.pull,!0),s.checkPut=e(r.put),s.revertClone=r.revertClone,t.group=s},At=function(){!Ft&&X&&$(X,"display","none")},Nt=function(){!Ft&&X&&$(X,"display","")};function Rt(t){if(q){t=t.touches?t.touches[0]:t;var e=(r=t.clientX,a=t.clientY,bt.some(function(t){if((s=t[L].options.emptyInsertThreshold)&&!M(t)){var e=C(t),i=r>=e.left-s&&r<=e.right+s,s=a>=e.top-s&&a<=e.bottom+s;return i&&s?o=t:void 0}}),o);if(e){var i,s={};for(i in t)t.hasOwnProperty(i)&&(s[i]=t[i]);s.target=s.rootEl=e,s.preventDefault=void 0,s.stopPropagation=void 0,e[L]._onDragOver(s)}}var r,a,o}function Ot(t){q&&q.parentNode[L]._isOutsideThisEl(t.target)}function Bt(t,i){if(!t||!t.nodeType||1!==t.nodeType)throw"Sortable: `el` must be an HTMLElement, not ".concat({}.toString.call(t));this.el=t,this.options=i=s({},i),t[L]=this;var r,a,o={group:null,sort:!0,disabled:!1,store:null,handle:null,draggable:/^[uo]l$/i.test(t.nodeName)?">li":">*",swapThreshold:1,invertSwap:!1,invertedSwapThreshold:null,removeCloneOnHide:!0,direction:function(){return It(t,this.options)},ghostClass:"sortable-ghost",chosenClass:"sortable-chosen",dragClass:"sortable-drag",ignore:"a, img",filter:null,preventOnFilter:!0,animation:0,easing:null,setData:function(t,e){t.setData("Text",e.textContent)},dropBubble:!1,dragoverBubble:!1,dataIdAttr:"data-id",delay:0,delayOnTouchOnly:!1,touchStartThreshold:(Number.parseInt?Number:window).parseInt(window.devicePixelRatio,10)||1,forceFallback:!1,fallbackClass:"sortable-fallback",fallbackOnBody:!1,fallbackTolerance:0,fallbackOffset:{x:0,y:0},supportPointer:!1!==Bt.supportPointer&&"PointerEvent"in window&&(!d||p),emptyInsertThreshold:5};for(r in W.initializePlugins(this,t,o),o)r in i||(i[r]=o[r]);for(a in Tt(i),this)"_"===a.charAt(0)&&"function"==typeof this[a]&&(this[a]=this[a].bind(this));this.nativeDraggable=!i.forceFallback&&Dt,this.nativeDraggable&&(this.options.touchStartThreshold=1),i.supportPointer?g(t,"pointerdown",this._onTapStart):(g(t,"mousedown",this._onTapStart),g(t,"touchstart",this._onTapStart)),this.nativeDraggable&&(g(t,"dragover",this),g(t,"dragenter",this)),bt.push(this.el),i.store&&i.store.get&&this.sort(i.store.get(this)||[]),s(this,function(){var t,i=[];return{captureAnimationState:function(){i=[],this.options.animation&&[].slice.call(this.el.children).forEach(function(t){var s,r;"none"!==$(t,"display")&&t!==Bt.ghost&&(i.push({target:t,rect:C(t)}),s=e({},i[i.length-1].rect),!t.thisAnimationDuration||(r=w(t,!0))&&(s.top-=r.f,s.left-=r.e),t.fromRect=s)})},addAnimationState:function(t){i.push(t)},removeAnimationState:function(t){i.splice(function(t,e){for(var i in t)if(t.hasOwnProperty(i))for(var s in e)if(e.hasOwnProperty(s)&&e[s]===t[i][s])return Number(i);return-1}(i,{target:t}),1)},animateAll:function(e){var s=this;if(!this.options.animation)return clearTimeout(t),void("function"==typeof e&&e());var r=!1,a=0;i.forEach(function(t){var e=0,i=t.target,o=i.fromRect,n=C(i),l=i.prevFromRect,c=i.prevToRect,d=t.rect,p=w(i,!0);p&&(n.top-=p.f,n.left-=p.e),i.toRect=n,i.thisAnimationDuration&&T(l,n)&&!T(o,n)&&(d.top-n.top)/(d.left-n.left)==(o.top-n.top)/(o.left-n.left)&&(t=d,p=l,l=c,c=s.options,e=Math.sqrt(Math.pow(p.top-t.top,2)+Math.pow(p.left-t.left,2))/Math.sqrt(Math.pow(p.top-l.top,2)+Math.pow(p.left-l.left,2))*c.animation),T(n,o)||(i.prevFromRect=o,i.prevToRect=n,e=e||s.options.animation,s.animate(i,d,n,e)),e&&(r=!0,a=Math.max(a,e),clearTimeout(i.animationResetTimer),i.animationResetTimer=setTimeout(function(){i.animationTime=0,i.prevFromRect=null,i.fromRect=null,i.prevToRect=null,i.thisAnimationDuration=null},e),i.thisAnimationDuration=e)}),clearTimeout(t),r?t=setTimeout(function(){"function"==typeof e&&e()},a):"function"==typeof e&&e(),i=[]},animate:function(t,e,i,s){var r,a;s&&($(t,"transition",""),$(t,"transform",""),r=(a=w(this.el))&&a.a,a=a&&a.d,r=(e.left-i.left)/(r||1),a=(e.top-i.top)/(a||1),t.animatingX=!!r,t.animatingY=!!a,$(t,"transform","translate3d("+r+"px,"+a+"px,0)"),this.forRepaintDummy=t.offsetWidth,$(t,"transition","transform "+s+"ms"+(this.options.easing?" "+this.options.easing:"")),$(t,"transform","translate3d(0,0,0)"),"number"==typeof t.animated&&clearTimeout(t.animated),t.animated=setTimeout(function(){$(t,"transition",""),$(t,"transform",""),t.animated=!1,t.animatingX=!1,t.animatingY=!1},s))}}}())}function Pt(t,e,i,s,r,a,o,c){var d,p,h=t[L],_=h.options.onMove;return!window.CustomEvent||n||l?(d=document.createEvent("Event")).initEvent("move",!0,!0):d=new CustomEvent("move",{bubbles:!0,cancelable:!0}),d.to=e,d.from=t,d.dragged=i,d.draggedRect=s,d.related=r||e,d.relatedRect=a||C(e),d.willInsertAfter=c,d.originalEvent=o,t.dispatchEvent(d),_?_.call(h,d,o):p}function Lt(t){t.draggable=!1}function Ht(){St=!1}function Ut(t){return setTimeout(t,0)}function Wt(t){return clearTimeout(t)}Et&&!h&&document.addEventListener("click",function(t){if(xt)return t.preventDefault(),t.stopPropagation&&t.stopPropagation(),t.stopImmediatePropagation&&t.stopImmediatePropagation(),xt=!1},!0),Bt.prototype={constructor:Bt,_isOutsideThisEl:function(t){this.el.contains(t)||t===this.el||(ut=null)},_getDirection:function(t,e){return"function"==typeof this.options.direction?this.options.direction.call(this,t,e,q):this.options.direction},_onTapStart:function(t){if(t.cancelable){var e=this,i=this.el,s=this.options,r=s.preventOnFilter,a=t.type,o=t.touches&&t.touches[0]||t.pointerType&&"touch"===t.pointerType&&t,n=(o||t).target,l=t.target.shadowRoot&&(t.path&&t.path[0]||t.composedPath&&t.composedPath()[0])||n,c=s.filter;if(function(t){Ct.length=0;for(var e=t.getElementsByTagName("input"),i=e.length;i--;){var s=e[i];s.checked&&Ct.push(s)}}(i),!q&&!(/mousedown|pointerdown/.test(a)&&0!==t.button||s.disabled)&&!l.isContentEditable&&(this.nativeDraggable||!d||!n||"SELECT"!==n.tagName.toUpperCase())&&!((n=v(n,s.draggable,i,!1))&&n.animated||Q===n)){if(it=D(n),rt=D(n,s.draggable),"function"==typeof c){if(c.call(this,t,n,this))return V({sortable:e,rootEl:l,name:"filter",targetEl:n,toEl:i,fromEl:i}),G("filter",e,{evt:t}),void(r&&t.preventDefault())}else if(c=c&&c.split(",").some(function(s){if(s=v(l,s.trim(),i,!1))return V({sortable:e,rootEl:s,name:"filter",targetEl:n,fromEl:i,toEl:i}),G("filter",e,{evt:t}),!0}))return void(r&&t.preventDefault());s.handle&&!v(l,s.handle,i,!1)||this._prepareDragStart(t,o,n)}}},_prepareDragStart:function(t,e,i){var s,r=this,a=r.el,o=r.options,d=a.ownerDocument;i&&!q&&i.parentNode===a&&(s=C(i),Z=a,Y=(q=i).parentNode,J=q.nextSibling,Q=i,ot=o.group,lt={target:Bt.dragged=q,clientX:(e||t).clientX,clientY:(e||t).clientY},ht=lt.clientX-s.left,_t=lt.clientY-s.top,this._lastX=(e||t).clientX,this._lastY=(e||t).clientY,q.style["will-change"]="all",s=function(){G("delayEnded",r,{evt:t}),Bt.eventCanceled?r._onDrop():(r._disableDelayedDragEvents(),!c&&r.nativeDraggable&&(q.draggable=!0),r._triggerDragStart(t,e),V({sortable:r,name:"choose",originalEvent:t}),b(q,o.chosenClass,!0))},o.ignore.split(",").forEach(function(t){k(q,t.trim(),Lt)}),g(d,"dragover",Rt),g(d,"mousemove",Rt),g(d,"touchmove",Rt),o.supportPointer?(g(d,"pointerup",r._onDrop),this.nativeDraggable||g(d,"pointercancel",r._onDrop)):(g(d,"mouseup",r._onDrop),g(d,"touchend",r._onDrop),g(d,"touchcancel",r._onDrop)),c&&this.nativeDraggable&&(this.options.touchStartThreshold=4,q.draggable=!0),G("delayStart",this,{evt:t}),!o.delay||o.delayOnTouchOnly&&!e||this.nativeDraggable&&(l||n)?s():Bt.eventCanceled?this._onDrop():(o.supportPointer?(g(d,"pointerup",r._disableDelayedDrag),g(d,"pointercancel",r._disableDelayedDrag)):(g(d,"mouseup",r._disableDelayedDrag),g(d,"touchend",r._disableDelayedDrag),g(d,"touchcancel",r._disableDelayedDrag)),g(d,"mousemove",r._delayedDragTouchMoveHandler),g(d,"touchmove",r._delayedDragTouchMoveHandler),o.supportPointer&&g(d,"pointermove",r._delayedDragTouchMoveHandler),r._dragStartTimer=setTimeout(s,o.delay)))},_delayedDragTouchMoveHandler:function(t){t=t.touches?t.touches[0]:t,Math.max(Math.abs(t.clientX-this._lastX),Math.abs(t.clientY-this._lastY))>=Math.floor(this.options.touchStartThreshold/(this.nativeDraggable&&window.devicePixelRatio||1))&&this._disableDelayedDrag()},_disableDelayedDrag:function(){q&&Lt(q),clearTimeout(this._dragStartTimer),this._disableDelayedDragEvents()},_disableDelayedDragEvents:function(){var t=this.el.ownerDocument;u(t,"mouseup",this._disableDelayedDrag),u(t,"touchend",this._disableDelayedDrag),u(t,"touchcancel",this._disableDelayedDrag),u(t,"pointerup",this._disableDelayedDrag),u(t,"pointercancel",this._disableDelayedDrag),u(t,"mousemove",this._delayedDragTouchMoveHandler),u(t,"touchmove",this._delayedDragTouchMoveHandler),u(t,"pointermove",this._delayedDragTouchMoveHandler)},_triggerDragStart:function(t,e){e=e||"touch"==t.pointerType&&t,!this.nativeDraggable||e?this.options.supportPointer?g(document,"pointermove",this._onTouchMove):g(document,e?"touchmove":"mousemove",this._onTouchMove):(g(q,"dragend",this),g(Z,"dragstart",this._onDragStart));try{document.selection?Ut(function(){document.selection.empty()}):window.getSelection().removeAllRanges()}catch(t){}},_dragStarted:function(t,e){var i;yt=!1,Z&&q?(G("dragStarted",this,{evt:e}),this.nativeDraggable&&g(document,"dragover",Ot),i=this.options,t||b(q,i.dragClass,!1),b(q,i.ghostClass,!0),Bt.active=this,t&&this._appendGhost(),V({sortable:this,name:"start",originalEvent:e})):this._nulling()},_emulateDragOver:function(){if(ct){this._lastX=ct.clientX,this._lastY=ct.clientY,At();for(var t=document.elementFromPoint(ct.clientX,ct.clientY),e=t;t&&t.shadowRoot&&(t=t.shadowRoot.elementFromPoint(ct.clientX,ct.clientY))!==e;)e=t;if(q.parentNode[L]._isOutsideThisEl(t),e)do{if(e[L]&&e[L]._onDragOver({clientX:ct.clientX,clientY:ct.clientY,target:t,rootEl:e})&&!this.options.dragoverBubble)break}while(e=m(t=e));Nt()}},_onTouchMove:function(t){if(lt){var e=(n=this.options).fallbackTolerance,i=n.fallbackOffset,s=t.touches?t.touches[0]:t,r=X&&w(X,!0),a=X&&r&&r.a,o=X&&r&&r.d,n=zt&&vt&&F(vt);a=(s.clientX-lt.clientX+i.x)/(a||1)+(n?n[0]-kt[0]:0)/(a||1),o=(s.clientY-lt.clientY+i.y)/(o||1)+(n?n[1]-kt[1]:0)/(o||1);if(!Bt.active&&!yt){if(e&&Math.max(Math.abs(s.clientX-this._lastX),Math.abs(s.clientY-this._lastY))<e)return;this._onDragStart(t,!0)}X&&(r?(r.e+=a-(dt||0),r.f+=o-(pt||0)):r={a:1,b:0,c:0,d:1,e:a,f:o},r="matrix(".concat(r.a,",").concat(r.b,",").concat(r.c,",").concat(r.d,",").concat(r.e,",").concat(r.f,")"),$(X,"webkitTransform",r),$(X,"mozTransform",r),$(X,"msTransform",r),$(X,"transform",r),dt=a,pt=o,ct=s),t.cancelable&&t.preventDefault()}},_appendGhost:function(){if(!X){var t=this.options.fallbackOnBody?document.body:Z,e=C(q,!0,zt,!0,t),i=this.options;if(zt){for(vt=t;"static"===$(vt,"position")&&"none"===$(vt,"transform")&&vt!==document;)vt=vt.parentNode;vt!==document.body&&vt!==document.documentElement?(vt===document&&(vt=S()),e.top+=vt.scrollTop,e.left+=vt.scrollLeft):vt=S(),kt=F(vt)}b(X=q.cloneNode(!0),i.ghostClass,!1),b(X,i.fallbackClass,!0),b(X,i.dragClass,!0),$(X,"transition",""),$(X,"transform",""),$(X,"box-sizing","border-box"),$(X,"margin",0),$(X,"top",e.top),$(X,"left",e.left),$(X,"width",e.width),$(X,"height",e.height),$(X,"opacity","0.8"),$(X,"position",zt?"absolute":"fixed"),$(X,"zIndex","100000"),$(X,"pointerEvents","none"),Bt.ghost=X,t.appendChild(X),$(X,"transform-origin",ht/parseInt(X.style.width)*100+"% "+_t/parseInt(X.style.height)*100+"%")}},_onDragStart:function(t,e){var i=this,s=t.dataTransfer,r=i.options;G("dragStart",this,{evt:t}),Bt.eventCanceled?this._onDrop():(G("setupClone",this),Bt.eventCanceled||((tt=R(q)).removeAttribute("id"),tt.draggable=!1,tt.style["will-change"]="",this._hideClone(),b(tt,this.options.chosenClass,!1),Bt.clone=tt),i.cloneId=Ut(function(){G("clone",i),Bt.eventCanceled||(i.options.removeCloneOnHide||Z.insertBefore(tt,q),i._hideClone(),V({sortable:i,name:"clone"}))}),e||b(q,r.dragClass,!0),e?(xt=!0,i._loopId=setInterval(i._emulateDragOver,50)):(u(document,"mouseup",i._onDrop),u(document,"touchend",i._onDrop),u(document,"touchcancel",i._onDrop),s&&(s.effectAllowed="move",r.setData&&r.setData.call(i,s,q)),g(document,"drop",i),$(q,"transform","translateZ(0)")),yt=!0,i._dragStartId=Ut(i._dragStarted.bind(i,e,t)),g(document,"selectstart",i),gt=!0,window.getSelection().removeAllRanges(),d&&$(document.body,"user-select","none"))},_onDragOver:function(t){var i,s,r,a,o,n=this.el,l=t.target,c=this.options,d=c.group,p=Bt.active,h=ot===d,_=c.sort,g=nt||p,u=this,f=!1;if(!St){if(void 0!==t.preventDefault&&t.cancelable&&t.preventDefault(),l=v(l,c.draggable,n,!0),B("dragOver"),Bt.eventCanceled)return f;if(q.contains(t.target)||l.animated&&l.animatingX&&l.animatingY||u._ignoreWhileAnimating===l)return U(!1);if(xt=!1,p&&!c.disabled&&(h?_||(s=Y!==Z):nt===this||(this.lastPutMode=ot.checkPull(this,p,q,t))&&d.checkPut(this,p,q,t))){if(r="vertical"===this._getDirection(t,l),i=C(q),B("dragOverValid"),Bt.eventCanceled)return f;if(s)return Y=Z,H(),this._hideClone(),B("revert"),Bt.eventCanceled||(J?Z.insertBefore(q,J):Z.appendChild(q)),U(!0);var m=M(n,c.draggable);if(m&&(F=t,d=r,O=C(M((S=this).el,S.options.draggable)),S=P(S.el,S.options,X),!(d?F.clientX>S.right+10||F.clientY>O.bottom&&F.clientX>O.left:F.clientY>S.bottom+10||F.clientX>O.right&&F.clientY>O.top)||m.animated)){if(m&&(a=t,o=r,T=C(z((I=this).el,0,I.options,!0)),I=P(I.el,I.options,X),o?a.clientX<I.left-10||a.clientY<T.top&&a.clientX<T.right:a.clientY<I.top-10||a.clientY<T.bottom&&a.clientX<T.left)){if((A=z(n,0,c,!0))===q)return U(!1);if(k=C(l=A),!1!==Pt(Z,n,q,i,l,k,t,!1))return H(),n.insertBefore(q,A),Y=n,W(),U(!0)}else if(l.parentNode===n){var y,x,w,k=C(l),S=q.parentNode!==n,F=(F=q.animated&&q.toRect||i,O=l.animated&&l.toRect||k,I=(o=r)?F.left:F.top,a=o?F.right:F.bottom,T=o?F.width:F.height,A=o?O.left:O.top,F=o?O.right:O.bottom,O=o?O.width:O.height,!(I===A||a===F||I+T/2===A+O/2)),I=r?"top":"left",T=E(l,"top","top")||E(q,"top","top"),A=T?T.scrollTop:void 0;if(ut!==l&&(x=k[I],$t=!1,wt=!F&&c.invertSwap||S),0!==(y=function(t,e,i,s,r,a,o,n){var l=s?t.clientY:t.clientX,c=s?i.height:i.width;t=s?i.top:i.left,s=s?i.bottom:i.right,i=!1;if(!o)if(n&&mt<c*r){if($t=!$t&&(1===ft?t+c*a/2<l:l<s-c*a/2)||$t)i=!0;else if(1===ft?l<t+mt:s-mt<l)return-ft}else if(t+c*(1-r)/2<l&&l<s-c*(1-r)/2)return function(t){return D(q)<D(t)?1:-1}(e);return(i=i||o)&&(l<t+c*a/2||s-c*a/2<l)?t+c/2<l?1:-1:0}(t,l,k,r,F?1:c.swapThreshold,null==c.invertedSwapThreshold?c.swapThreshold:c.invertedSwapThreshold,wt,ut===l)))for(var R=D(q);(w=Y.children[R-=y])&&("none"===$(w,"display")||w===X););if(0===y||w===l)return U(!1);ft=y;var O=(ut=l).nextElementSibling;S=!1;if(!1!==(F=Pt(Z,n,q,i,l,k,t,S=1===y)))return 1!==F&&-1!==F||(S=1===F),St=!0,setTimeout(Ht,30),H(),S&&!O?n.appendChild(q):l.parentNode.insertBefore(q,S?O:l),T&&N(T,0,A-T.scrollTop),Y=q.parentNode,void 0===x||wt||(mt=Math.abs(x-C(l)[I])),W(),U(!0)}}else{if(m===q)return U(!1);if((l=m&&n===t.target?m:l)&&(k=C(l)),!1!==Pt(Z,n,q,i,l,k,t,!!l))return H(),m&&m.nextSibling?n.insertBefore(q,m.nextSibling):n.appendChild(q),Y=n,W(),U(!0)}if(n.contains(q))return U(!1)}return!1}function B(a,o){G(a,u,e({evt:t,isOwner:h,axis:r?"vertical":"horizontal",revert:s,dragRect:i,targetRect:k,canSort:_,fromSortable:g,target:l,completed:U,onMove:function(e,s){return Pt(Z,n,q,i,e,C(e),t,s)},changed:W},o))}function H(){B("dragOverAnimationCapture"),u.captureAnimationState(),u!==g&&g.captureAnimationState()}function U(e){return B("dragOverCompleted",{insertion:e}),e&&(h?p._hideClone():p._showClone(u),u!==g&&(b(q,(nt||p).options.ghostClass,!1),b(q,c.ghostClass,!0)),nt!==u&&u!==Bt.active?nt=u:u===Bt.active&&nt&&(nt=null),g===u&&(u._ignoreWhileAnimating=l),u.animateAll(function(){B("dragOverAnimationComplete"),u._ignoreWhileAnimating=null}),u!==g&&(g.animateAll(),g._ignoreWhileAnimating=null)),(l===q&&!q.animated||l===n&&!l.animated)&&(ut=null),c.dragoverBubble||t.rootEl||l===document||(q.parentNode[L]._isOutsideThisEl(t.target),e||Rt(t)),!c.dragoverBubble&&t.stopPropagation&&t.stopPropagation(),f=!0}function W(){st=D(q),at=D(q,c.draggable),V({sortable:u,name:"change",toEl:n,newIndex:st,newDraggableIndex:at,originalEvent:t})}},_ignoreWhileAnimating:null,_offMoveEvents:function(){u(document,"mousemove",this._onTouchMove),u(document,"touchmove",this._onTouchMove),u(document,"pointermove",this._onTouchMove),u(document,"dragover",Rt),u(document,"mousemove",Rt),u(document,"touchmove",Rt)},_offUpEvents:function(){var t=this.el.ownerDocument;u(t,"mouseup",this._onDrop),u(t,"touchend",this._onDrop),u(t,"pointerup",this._onDrop),u(t,"pointercancel",this._onDrop),u(t,"touchcancel",this._onDrop),u(document,"selectstart",this)},_onDrop:function(t){var e=this.el,i=this.options;st=D(q),at=D(q,i.draggable),G("drop",this,{evt:t}),Y=q&&q.parentNode,st=D(q),at=D(q,i.draggable),Bt.eventCanceled||($t=wt=yt=!1,clearInterval(this._loopId),clearTimeout(this._dragStartTimer),Wt(this.cloneId),Wt(this._dragStartId),this.nativeDraggable&&(u(document,"drop",this),u(e,"dragstart",this._onDragStart)),this._offMoveEvents(),this._offUpEvents(),d&&$(document.body,"user-select",""),$(q,"transform",""),t&&(gt&&(t.cancelable&&t.preventDefault(),i.dropBubble||t.stopPropagation()),X&&X.parentNode&&X.parentNode.removeChild(X),(Z===Y||nt&&"clone"!==nt.lastPutMode)&&tt&&tt.parentNode&&tt.parentNode.removeChild(tt),q&&(this.nativeDraggable&&u(q,"dragend",this),Lt(q),q.style["will-change"]="",gt&&!yt&&b(q,(nt||this).options.ghostClass,!1),b(q,this.options.chosenClass,!1),V({sortable:this,name:"unchoose",toEl:Y,newIndex:null,newDraggableIndex:null,originalEvent:t}),Z!==Y?(0<=st&&(V({rootEl:Y,name:"add",toEl:Y,fromEl:Z,originalEvent:t}),V({sortable:this,name:"remove",toEl:Y,originalEvent:t}),V({rootEl:Y,name:"sort",toEl:Y,fromEl:Z,originalEvent:t}),V({sortable:this,name:"sort",toEl:Y,originalEvent:t})),nt&&nt.save()):st!==it&&0<=st&&(V({sortable:this,name:"update",toEl:Y,originalEvent:t}),V({sortable:this,name:"sort",toEl:Y,originalEvent:t})),Bt.active&&(null!=st&&-1!==st||(st=it,at=rt),V({sortable:this,name:"end",toEl:Y,originalEvent:t}),this.save())))),this._nulling()},_nulling:function(){G("nulling",this),Z=q=Y=X=J=tt=Q=et=lt=ct=gt=st=at=it=rt=ut=ft=nt=ot=Bt.dragged=Bt.ghost=Bt.clone=Bt.active=null,Ct.forEach(function(t){t.checked=!0}),Ct.length=dt=pt=0},handleEvent:function(t){switch(t.type){case"drop":case"dragend":this._onDrop(t);break;case"dragenter":case"dragover":q&&(this._onDragOver(t),function(t){t.dataTransfer&&(t.dataTransfer.dropEffect="move"),t.cancelable&&t.preventDefault()}(t));break;case"selectstart":t.preventDefault()}},toArray:function(){for(var t,e=[],i=this.el.children,s=0,r=i.length,a=this.options;s<r;s++)v(t=i[s],a.draggable,this.el,!1)&&e.push(t.getAttribute(a.dataIdAttr)||function(t){for(var e=t.tagName+t.className+t.src+t.href+t.textContent,i=e.length,s=0;i--;)s+=e.charCodeAt(i);return s.toString(36)}(t));return e},sort:function(t,e){var i={},s=this.el;this.toArray().forEach(function(t,e){v(e=s.children[e],this.options.draggable,s,!1)&&(i[t]=e)},this),e&&this.captureAnimationState(),t.forEach(function(t){i[t]&&(s.removeChild(i[t]),s.appendChild(i[t]))}),e&&this.animateAll()},save:function(){var t=this.options.store;t&&t.set&&t.set(this)},closest:function(t,e){return v(t,e||this.options.draggable,this.el,!1)},option:function(t,e){var i=this.options;if(void 0===e)return i[t];var s=W.modifyOption(this,t,e);i[t]=void 0!==s?s:e,"group"===t&&Tt(i)},destroy:function(){G("destroy",this);var t=this.el;t[L]=null,u(t,"mousedown",this._onTapStart),u(t,"touchstart",this._onTapStart),u(t,"pointerdown",this._onTapStart),this.nativeDraggable&&(u(t,"dragover",this),u(t,"dragenter",this)),Array.prototype.forEach.call(t.querySelectorAll("[draggable]"),function(t){t.removeAttribute("draggable")}),this._onDrop(),this._disableDelayedDragEvents(),bt.splice(bt.indexOf(this.el),1),this.el=t=null},_hideClone:function(){et||(G("hideClone",this),Bt.eventCanceled||($(tt,"display","none"),this.options.removeCloneOnHide&&tt.parentNode&&tt.parentNode.removeChild(tt),et=!0))},_showClone:function(t){"clone"===t.lastPutMode?et&&(G("showClone",this),Bt.eventCanceled||(q.parentNode!=Z||this.options.group.revertClone?J?Z.insertBefore(tt,J):Z.appendChild(tt):Z.insertBefore(tt,q),this.options.group.revertClone&&this.animate(q,tt),$(tt,"display",""),et=!1)):this._hideClone()}},Et&&g(document,"touchmove",function(t){(Bt.active||yt)&&t.cancelable&&t.preventDefault()}),Bt.utils={on:g,off:u,css:$,find:k,is:function(t,e){return!!v(t,e,t,!1)},extend:function(t,e){if(t&&e)for(var i in e)e.hasOwnProperty(i)&&(t[i]=e[i]);return t},throttle:A,closest:v,toggleClass:b,clone:R,index:D,nextTick:Ut,cancelNextTick:Wt,detectDirection:It,getChild:z,expando:L},Bt.get=function(t){return t[L]},Bt.mount=function(){for(var t=arguments.length,i=new Array(t),s=0;s<t;s++)i[s]=arguments[s];(i=i[0].constructor===Array?i[0]:i).forEach(function(t){if(!t.prototype||!t.prototype.constructor)throw"Sortable: Mounted plugin must be a constructor function, not ".concat({}.toString.call(t));t.utils&&(Bt.utils=e(e({},Bt.utils),t.utils)),W.mount(t)})},Bt.create=function(t,e){return new Bt(t,e)};var jt,Gt,Kt,Vt,qt,Yt,Xt=[],Zt=!(Bt.version="1.15.6");function Jt(){Xt.forEach(function(t){clearInterval(t.pid)}),Xt=[]}function Qt(){clearInterval(Yt)}var te,ee=A(function(t,e,i,s){if(e.scroll){var r,a=(t.touches?t.touches[0]:t).clientX,o=(t.touches?t.touches[0]:t).clientY,n=e.scrollSensitivity,l=e.scrollSpeed,c=S(),d=!1;Gt!==i&&(Gt=i,Jt(),jt=e.scroll,r=e.scrollFn,!0===jt&&(jt=I(i,!0)));var p=0,h=jt;do{var _=h,g=(z=C(_)).top,u=z.bottom,f=z.left,m=z.right,v=z.width,y=z.height,x=void 0,b=_.scrollWidth,w=_.scrollHeight,k=$(_),E=_.scrollLeft,z=_.scrollTop,M=_===c?(x=v<b&&("auto"===k.overflowX||"scroll"===k.overflowX||"visible"===k.overflowX),y<w&&("auto"===k.overflowY||"scroll"===k.overflowY||"visible"===k.overflowY)):(x=v<b&&("auto"===k.overflowX||"scroll"===k.overflowX),y<w&&("auto"===k.overflowY||"scroll"===k.overflowY));E=x&&(Math.abs(m-a)<=n&&E+v<b)-(Math.abs(f-a)<=n&&!!E),z=M&&(Math.abs(u-o)<=n&&z+y<w)-(Math.abs(g-o)<=n&&!!z);if(!Xt[p])for(var D=0;D<=p;D++)Xt[D]||(Xt[D]={});Xt[p].vx==E&&Xt[p].vy==z&&Xt[p].el===_||(Xt[p].el=_,Xt[p].vx=E,Xt[p].vy=z,clearInterval(Xt[p].pid),0==E&&0==z||(d=!0,Xt[p].pid=setInterval(function(){s&&0===this.layer&&Bt.active._onTouchMove(qt);var e=Xt[this.layer].vy?Xt[this.layer].vy*l:0,i=Xt[this.layer].vx?Xt[this.layer].vx*l:0;"function"==typeof r&&"continue"!==r.call(Bt.dragged.parentNode[L],i,e,t,qt,Xt[this.layer].el)||N(Xt[this.layer].el,i,e)}.bind({layer:p}),24))),p++}while(e.bubbleScroll&&h!==c&&(h=I(h,!1)));Zt=d}},30);h=function(t){var e=t.originalEvent,i=t.putSortable,s=t.dragEl,r=t.activeSortable,a=t.dispatchSortableEvent,o=t.hideGhostForTarget;t=t.unhideGhostForTarget;e&&(r=i||r,o(),e=e.changedTouches&&e.changedTouches.length?e.changedTouches[0]:e,e=document.elementFromPoint(e.clientX,e.clientY),t(),r&&!r.el.contains(e)&&(a("spill"),this.onSpill({dragEl:s,putSortable:i})))};function ie(){}function se(){}ie.prototype={startIndex:null,dragStart:function(t){t=t.oldDraggableIndex,this.startIndex=t},onSpill:function(t){var e=t.dragEl,i=t.putSortable;this.sortable.captureAnimationState(),i&&i.captureAnimationState(),(t=z(this.sortable.el,this.startIndex,this.options))?this.sortable.el.insertBefore(e,t):this.sortable.el.appendChild(e),this.sortable.animateAll(),i&&i.animateAll()},drop:h},s(ie,{pluginName:"revertOnSpill"}),se.prototype={onSpill:function(t){var e=t.dragEl;(t=t.putSortable||this.sortable).captureAnimationState(),e.parentNode&&e.parentNode.removeChild(e),t.animateAll()},drop:h},s(se,{pluginName:"removeOnSpill"});var re,ae,oe,ne,le,ce=[],de=[],pe=!1,he=!1,_e=!1;function ge(t,e){de.forEach(function(i,s){(s=e.children[i.sortableIndex+(t?Number(s):0)])?e.insertBefore(i,s):e.appendChild(i)})}function ue(){ce.forEach(function(t){t!==oe&&t.parentNode&&t.parentNode.removeChild(t)})}return Bt.mount(new function(){function t(){for(var t in this.defaults={scroll:!0,forceAutoScrollFallback:!1,scrollSensitivity:30,scrollSpeed:10,bubbleScroll:!0},this)"_"===t.charAt(0)&&"function"==typeof this[t]&&(this[t]=this[t].bind(this))}return t.prototype={dragStarted:function(t){t=t.originalEvent,this.sortable.nativeDraggable?g(document,"dragover",this._handleAutoScroll):this.options.supportPointer?g(document,"pointermove",this._handleFallbackAutoScroll):t.touches?g(document,"touchmove",this._handleFallbackAutoScroll):g(document,"mousemove",this._handleFallbackAutoScroll)},dragOverCompleted:function(t){t=t.originalEvent,this.options.dragOverBubble||t.rootEl||this._handleAutoScroll(t)},drop:function(){this.sortable.nativeDraggable?u(document,"dragover",this._handleAutoScroll):(u(document,"pointermove",this._handleFallbackAutoScroll),u(document,"touchmove",this._handleFallbackAutoScroll),u(document,"mousemove",this._handleFallbackAutoScroll)),Qt(),Jt(),clearTimeout(y),y=void 0},nulling:function(){qt=Gt=jt=Zt=Yt=Kt=Vt=null,Xt.length=0},_handleFallbackAutoScroll:function(t){this._handleAutoScroll(t,!0)},_handleAutoScroll:function(t,e){var i,s=this,r=(t.touches?t.touches[0]:t).clientX,a=(t.touches?t.touches[0]:t).clientY,o=document.elementFromPoint(r,a);qt=t,e||this.options.forceAutoScrollFallback||l||n||d?(ee(t,this.options,o,e),i=I(o,!0),!Zt||Yt&&r===Kt&&a===Vt||(Yt&&Qt(),Yt=setInterval(function(){var o=I(document.elementFromPoint(r,a),!0);o!==i&&(i=o,Jt()),ee(t,s.options,o,e)},10),Kt=r,Vt=a)):this.options.bubbleScroll&&I(o,!0)!==S()?ee(t,this.options,I(o,!1),!1):Jt()}},s(t,{pluginName:"scroll",initializeByDefault:!0})}),Bt.mount(se,ie),Bt.mount(new function(){function t(){this.defaults={swapClass:"sortable-swap-highlight"}}return t.prototype={dragStart:function(t){t=t.dragEl,te=t},dragOverValid:function(t){var e=t.completed,i=t.target,s=t.onMove,r=t.activeSortable,a=t.changed,o=t.cancel;r.options.swap&&(t=this.sortable.el,r=this.options,i&&i!==t&&(t=te,te=!1!==s(i)?(b(i,r.swapClass,!0),i):null,t&&t!==te&&b(t,r.swapClass,!1)),a(),e(!0),o())},drop:function(t){var e,i,s=t.activeSortable,r=t.putSortable,a=t.dragEl,o=r||this.sortable,n=this.options;te&&b(te,n.swapClass,!1),te&&(n.swap||r&&r.options.swap)&&a!==te&&(o.captureAnimationState(),o!==s&&s.captureAnimationState(),i=te,t=(e=a).parentNode,n=i.parentNode,t&&n&&!t.isEqualNode(i)&&!n.isEqualNode(e)&&(r=D(e),a=D(i),t.isEqualNode(n)&&r<a&&a++,t.insertBefore(i,t.children[r]),n.insertBefore(e,n.children[a])),o.animateAll(),o!==s&&s.animateAll())},nulling:function(){te=null}},s(t,{pluginName:"swap",eventProperties:function(){return{swapItem:te}}})}),Bt.mount(new function(){function t(t){for(var e in this)"_"===e.charAt(0)&&"function"==typeof this[e]&&(this[e]=this[e].bind(this));t.options.avoidImplicitDeselect||(t.options.supportPointer?g(document,"pointerup",this._deselectMultiDrag):(g(document,"mouseup",this._deselectMultiDrag),g(document,"touchend",this._deselectMultiDrag))),g(document,"keydown",this._checkKeyDown),g(document,"keyup",this._checkKeyUp),this.defaults={selectedClass:"sortable-selected",multiDragKey:null,avoidImplicitDeselect:!1,setData:function(e,i){var s="";ce.length&&ae===t?ce.forEach(function(t,e){s+=(e?", ":"")+t.textContent}):s=i.textContent,e.setData("Text",s)}}}return t.prototype={multiDragKeyDown:!1,isMultiDrag:!1,delayStartGlobal:function(t){t=t.dragEl,oe=t},delayEnded:function(){this.isMultiDrag=~ce.indexOf(oe)},setupClone:function(t){var e=t.sortable;t=t.cancel;if(this.isMultiDrag){for(var i=0;i<ce.length;i++)de.push(R(ce[i])),de[i].sortableIndex=ce[i].sortableIndex,de[i].draggable=!1,de[i].style["will-change"]="",b(de[i],this.options.selectedClass,!1),ce[i]===oe&&b(de[i],this.options.chosenClass,!1);e._hideClone(),t()}},clone:function(t){var e=t.sortable,i=t.rootEl,s=t.dispatchSortableEvent;t=t.cancel;this.isMultiDrag&&(this.options.removeCloneOnHide||ce.length&&ae===e&&(ge(!0,i),s("clone"),t()))},showClone:function(t){var e=t.cloneNowShown,i=t.rootEl;t=t.cancel;this.isMultiDrag&&(ge(!1,i),de.forEach(function(t){$(t,"display","")}),e(),le=!1,t())},hideClone:function(t){var e=this,i=(t.sortable,t.cloneNowHidden);t=t.cancel;this.isMultiDrag&&(de.forEach(function(t){$(t,"display","none"),e.options.removeCloneOnHide&&t.parentNode&&t.parentNode.removeChild(t)}),i(),le=!0,t())},dragStartGlobal:function(t){t.sortable,!this.isMultiDrag&&ae&&ae.multiDrag._deselectMultiDrag(),ce.forEach(function(t){t.sortableIndex=D(t)}),ce=ce.sort(function(t,e){return t.sortableIndex-e.sortableIndex}),_e=!0},dragStarted:function(t){var e,i=this;t=t.sortable;this.isMultiDrag&&(this.options.sort&&(t.captureAnimationState(),this.options.animation&&(ce.forEach(function(t){t!==oe&&$(t,"position","absolute")}),e=C(oe,!1,!0,!0),ce.forEach(function(t){t!==oe&&O(t,e)}),pe=he=!0)),t.animateAll(function(){pe=he=!1,i.options.animation&&ce.forEach(function(t){B(t)}),i.options.sort&&ue()}))},dragOver:function(t){var e=t.target,i=t.completed;t=t.cancel;he&&~ce.indexOf(e)&&(i(!1),t())},revert:function(t){var e,i,s=t.fromSortable,r=t.rootEl,a=t.sortable,o=t.dragRect;1<ce.length&&(ce.forEach(function(t){a.addAnimationState({target:t,rect:he?C(t):o}),B(t),t.fromRect=o,s.removeAnimationState(t)}),he=!1,e=!this.options.removeCloneOnHide,i=r,ce.forEach(function(t,s){(s=i.children[t.sortableIndex+(e?Number(s):0)])?i.insertBefore(t,s):i.appendChild(t)}))},dragOverCompleted:function(t){var e,i=t.sortable,s=t.isOwner,r=t.insertion,a=t.activeSortable,o=t.parentEl,n=t.putSortable;t=this.options;r&&(s&&a._hideClone(),pe=!1,t.animation&&1<ce.length&&(he||!s&&!a.options.sort&&!n)&&(e=C(oe,!1,!0,!0),ce.forEach(function(t){t!==oe&&(O(t,e),o.appendChild(t))}),he=!0),s||(he||ue(),1<ce.length?(s=le,a._showClone(i),a.options.animation&&!le&&s&&de.forEach(function(t){a.addAnimationState({target:t,rect:ne}),t.fromRect=ne,t.thisAnimationDuration=null})):a._showClone(i)))},dragOverAnimationCapture:function(t){var e=t.dragRect,i=t.isOwner;t=t.activeSortable;ce.forEach(function(t){t.thisAnimationDuration=null}),t.options.animation&&!i&&t.multiDrag.isMultiDrag&&(ne=s({},e),e=w(oe,!0),ne.top-=e.f,ne.left-=e.e)},dragOverAnimationComplete:function(){he&&(he=!1,ue())},drop:function(t){var e,i,s,r,a,o,n,l=t.originalEvent,c=t.rootEl,d=t.parentEl,p=t.sortable,h=t.dispatchSortableEvent,_=t.oldIndex,g=(t=t.putSortable)||this.sortable;l&&(e=this.options,i=d.children,_e||(e.multiDragKey&&!this.multiDragKeyDown&&this._deselectMultiDrag(),b(oe,e.selectedClass,!~ce.indexOf(oe)),~ce.indexOf(oe)?(ce.splice(ce.indexOf(oe),1),re=null,j({sortable:p,rootEl:c,name:"deselect",targetEl:oe,originalEvent:l})):(ce.push(oe),j({sortable:p,rootEl:c,name:"select",targetEl:oe,originalEvent:l}),l.shiftKey&&re&&p.el.contains(re)?(s=D(re),r=D(oe),~s&&~r&&s!==r&&function(){for(var t,a=s<r?(t=s,r):(t=r,s+1),o=e.filter;t<a;t++)~ce.indexOf(i[t])||v(i[t],e.draggable,d,!1)&&(o&&("function"==typeof o?o.call(p,l,i[t],p):o.split(",").some(function(e){return v(i[t],e.trim(),d,!1)}))||(b(i[t],e.selectedClass,!0),ce.push(i[t]),j({sortable:p,rootEl:c,name:"select",targetEl:i[t],originalEvent:l})))}()):re=oe,ae=g)),_e&&this.isMultiDrag&&(he=!1,(d[L].options.sort||d!==c)&&1<ce.length&&(a=C(oe),o=D(oe,":not(."+this.options.selectedClass+")"),!pe&&e.animation&&(oe.thisAnimationDuration=null),g.captureAnimationState(),pe||(e.animation&&(oe.fromRect=a,ce.forEach(function(t){var e;t.thisAnimationDuration=null,t!==oe&&(e=he?C(t):a,t.fromRect=e,g.addAnimationState({target:t,rect:e}))})),ue(),ce.forEach(function(t){i[o]?d.insertBefore(t,i[o]):d.appendChild(t),o++}),_===D(oe)&&(n=!1,ce.forEach(function(t){t.sortableIndex!==D(t)&&(n=!0)}),n&&(h("update"),h("sort")))),ce.forEach(function(t){B(t)}),g.animateAll()),ae=g),(c===d||t&&"clone"!==t.lastPutMode)&&de.forEach(function(t){t.parentNode&&t.parentNode.removeChild(t)}))},nullingGlobal:function(){this.isMultiDrag=_e=!1,de.length=0},destroyGlobal:function(){this._deselectMultiDrag(),u(document,"pointerup",this._deselectMultiDrag),u(document,"mouseup",this._deselectMultiDrag),u(document,"touchend",this._deselectMultiDrag),u(document,"keydown",this._checkKeyDown),u(document,"keyup",this._checkKeyUp)},_deselectMultiDrag:function(t){if(!(void 0!==_e&&_e||ae!==this.sortable||t&&v(t.target,this.options.draggable,this.sortable.el,!1)||t&&0!==t.button))for(;ce.length;){var e=ce[0];b(e,this.options.selectedClass,!1),ce.shift(),j({sortable:this.sortable,rootEl:this.sortable.el,name:"deselect",targetEl:e,originalEvent:t})}},_checkKeyDown:function(t){t.key===this.options.multiDragKey&&(this.multiDragKeyDown=!0)},_checkKeyUp:function(t){t.key===this.options.multiDragKey&&(this.multiDragKeyDown=!1)}},s(t,{pluginName:"multiDrag",utils:{select:function(t){var e=t.parentNode[L];e&&e.options.multiDrag&&!~ce.indexOf(t)&&(ae&&ae!==e&&(ae.multiDrag._deselectMultiDrag(),ae=e),b(t,e.options.selectedClass,!0),ce.push(t))},deselect:function(t){var e=t.parentNode[L],i=ce.indexOf(t);e&&e.options.multiDrag&&~i&&(b(t,e.options.selectedClass,!1),ce.splice(i,1))}},eventProperties:function(){var t=this,e=[],i=[];return ce.forEach(function(s){var r;e.push({multiDragElement:s,index:s.sortableIndex}),r=he&&s!==oe?-1:he?D(s,":not(."+t.options.selectedClass+")"):D(s),i.push({multiDragElement:s,index:r})}),{items:r(ce),clones:[].concat(de),oldIndicies:e,newIndicies:i}},optionListeners:{multiDragKey:function(t){return"ctrl"===(t=t.toLowerCase())?t="Control":1<t.length&&(t=t.charAt(0).toUpperCase()+t.substr(1)),t}}})}),Bt})}();const ke=Promise.resolve(window.Sortable);yt("sem-load-priority-card",class extends xt{constructor(){super(),this.devices=[],this.targetPeakLimit=5,this.currentPeak=0,this.loadManagementStatus="normal",this._sortable=null,this._interacting=!1,this._lastDeviceSig=""}setConfig(t){this._config=t,this.entityPrefix=t.entity_prefix||"sensor.sem_",this.requestUpdate()}set hass(t){this._hass,this._hass=t;const e=t?.language;if(e!==this._lang)return this._lang=e,this._lastDeviceSig="",void this.requestUpdate();if(this._interacting)return;if(this._isFrozen())return;const i=t?.states[`${this.entityPrefix}controllable_devices_count`],s=t?.states[`${this.entityPrefix}consecutive_peak_15min`],r=t?.states[`${this.entityPrefix}load_management_status`],a=(i?.state||"")+"|"+(s?.state||"")+"|"+(r?.state||"");a!==this._lastKey&&(this._lastKey=a,this._updateDeviceData(),this.requestUpdate())}get hass(){return this._hass}disconnectedCallback(){super.disconnectedCallback(),this._sortable&&(this._sortable.destroy(),this._sortable=null)}async firstUpdated(){await this._initSortable(),this._bindEvents()}async updated(t){const e=this.devices.map(t=>t.id).join(",");e!==this._lastDeviceSig&&(this._lastDeviceSig=e,this._sortable&&(this._sortable.destroy(),this._sortable=null),await this._initSortable(),this._bindEvents())}static get styles(){return a`
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
            .device.ghost { opacity:0.3; }
            .device.chosen { box-shadow:0 4px 20px rgba(0,0,0,0.15); border-color:#ff9800; z-index:10; }
            .device.dragging { opacity:0; }
            .device.moved { border-color:#ff9800; transition:border-color 0.1s ease; }
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
            .arrow-btn { border:none; background:none; cursor:pointer; font-size:10px; padding:0 4px; opacity:0.35; line-height:1; color:var(--primary-text-color,inherit); }
            .arrow-btn:hover { opacity:0.8; }
            .mode-select { background:var(--card-background-color,rgba(40,40,55,0.7)); color:var(--primary-text-color); border:1px solid var(--divider-color,rgba(255,255,255,0.08)); border-radius:6px; padding:2px 6px; font-size:13px; font-family:'Segoe UI','Roboto',sans-serif; cursor:pointer; -webkit-appearance:none; appearance:none; }
            .mode-select:focus { outline:none; border-color:rgba(255,152,0,0.5); }
            .configure-btn { display:inline-flex; align-items:center; gap:3px; padding:2px 6px; background:rgba(255,193,7,0.12); border:1px solid rgba(255,193,7,0.25); border-radius:5px; color:#ffc107; cursor:pointer; font-size:0.9em; }
            .configure-btn:hover { background:rgba(255,193,7,0.22); }
            .hint { text-align:center; font-size:0.95em; opacity:0.4; margin-top:10px; }
            .empty { text-align:center; padding:20px 0; opacity:0.4; font-size:1em; }
        `}_updateDeviceData(){if(!this._hass)return;const t=this._hass.states[`${this.entityPrefix}target_peak_limit`],e=this._hass.states[`${this.entityPrefix}consecutive_peak_15min`],i=this._hass.states[`${this.entityPrefix}load_management_status`],s=this._hass.states[`${this.entityPrefix}controllable_devices_count`];t&&(this.targetPeakLimit=parseFloat(t.state)||5),e&&(this.currentPeak=parseFloat(e.state)||0),i&&(this.loadManagementStatus=i.state||"normal"),s?.attributes?.devices&&(this.devices=Object.entries(s.attributes.devices).map(([t,e])=>({id:t,name:e.name||t.replace(/^(load_device_|energy_dashboard_)/,"").replace(/_/g," "),power:(e.current_power||0)/1e3,priority:e.priority||5,isOn:e.is_on||!1,isShed:e.is_shed||!1,shedReason:e.shed_reason||null,isControllable:!1!==e.is_controllable,isCritical:e.is_critical||!1,deviceType:e.device_type||"unknown",isAvailable:e.is_available||!1,hasManualMapping:e.has_manual_mapping||!1,energySensor:e.energy_sensor||"",control:e.control||null,controlEntity:e.control?.entity||e.switch_entity||"",controlType:e.control?.type||"switch",controlMode:e.control_mode||"peak_only",dependsOn:e.depends_on||[],blockedBy:e.blocked_by||null,icon:this._resolveDeviceIcon(e)})).sort((t,e)=>t.priority-e.priority))}render(){if(!this._config)return K;const t=this._getPeakColor(),e=this.targetPeakLimit-this.currentPeak,i=this.targetPeakLimit>0?Math.min(this.currentPeak/this.targetPeakLimit*100,100):0;return W`
            <ha-card>
                <div class="card-content">
                    <div class="status-bar">
                        <div class="peak-dot" style="background:${t};box-shadow:0 0 8px ${t}"></div>
                        <span id="lm-status" class="status-text">${this._t(this.loadManagementStatus||"normal").toUpperCase()}</span>
                        <div class="spacer"></div>
                        <span class="dim">${this._t("peak")}</span>
                        <span id="peak-current" class="mono">${this.currentPeak.toFixed(2)} kW</span>
                        <span class="dim">/ ${this.targetPeakLimit.toFixed(1)}</span>
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
                            <span id="peak-margin" class="mono" style="color:${e>0?"#4caf50":"#f44336"}">${e.toFixed(2)} kW</span>
                        </div>
                        <div class="bar">
                            <div id="peak-bar" class="bar-fill" style="width:${i}%;background:${t}"></div>
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

                    <div class="section-label">
                        <ha-icon icon="mdi:drag-vertical" style="--mdc-icon-size:18px"></ha-icon>
                        ${this._t("drag_to_reorder")}
                    </div>

                    <div id="device-list" class="device-list">
                        ${0===this.devices.length?W`<div class="empty">${this._t("no_devices_yet")}</div>`:this.devices.map((t,e)=>this._renderDevice(t,e+1))}
                    </div>

                    ${this.devices.length>0?W`<div class="hint">${this._t("drag_hint")}</div>`:K}

                    <div class="hint" style="margin-top:12px;padding:10px;background:rgba(128,128,128,0.06);border-radius:10px">
                        ${this._t("devices_auto_discovered")}
                    </div>
                </div>
            </ha-card>
        `}_renderDevice(t,e){const i=t.isOn||t.power>.01,s=t.dependsOn.length>0,r=this._getDependencyDepth(t),a=r>0?`margin-left:${24*r}px;border-left:2px solid rgba(255,152,0,${.3+.1*r});`:"";return W`
        <div class="device${s?" is-child":""}" data-id="${t.id}" style="${a}">
            <div class="drag-handle"
                 title="${s?this._t("locked_under_parent"):this._t("drag_to_reorder")}"
                 style="${s?"opacity:0.3;cursor:default":""}">${s?"·":"≡"}</div>
            <div class="device-body">
                <div class="device-top">
                    <div class="device-name">
                        ${s?W`<span style="color:#ff9800;font-size:12px;margin-right:4px">&#8618;</span>`:K}
                        <ha-icon icon="${t.icon}" style="--mdc-icon-size:20px;color:${i?"#ff9800":"#666"}"></ha-icon>
                        <span>${t.name}</span>
                        <span class="configure-btn" data-action="configure" data-energy="${t.energySensor}" data-name="${t.name}">
                            <ha-icon icon="mdi:${t.hasManualMapping?"wrench":"cog"}" style="--mdc-icon-size:14px"></ha-icon> ${t.isControllable?this._t("configure_device"):this._t("configure")}
                        </span>
                    </div>
                    <div class="device-power" data-field="power-${t.id}">
                        ${i?ht(1e3*t.power):t.isShed?this._t("shed_label"):this._t("off")}
                    </div>
                </div>
                ${t.blockedBy?W`<div style="font-size:13px;color:#ff9800;padding:2px 0 0 28px">&#9203; Waiting for: ${t.blockedBy}</div>`:K}
                ${t.dependsOn.length?W`<div style="font-size:13px;opacity:0.55;padding:0 0 0 28px">&#8618; ${this._t("requires")}: ${t.dependsOn.join(", ")}</div>`:K}
                ${t.isShed&&t.shedReason?W`<div style="font-size:13px;color:#f44336;padding:2px 0 0 28px">${"emergency"===t.shedReason?this._t("shed_emergency"):this._t("shed_peak")}</div>`:K}
                <div class="device-bottom">
                    <div class="status-dot ${i?"on":t.isShed?"shed":""}" data-field="status-${t.id}"></div>
                    <span class="dim" data-field="onoff-${t.id}">${i?this._t("on"):t.isShed?this._t("shed_label"):this._t("off")}</span>
                    <span class="badge priority" data-field="pri-${t.id}">${e}</span>
                    <div class="spacer"></div>
                    ${"ev_charger"===t.deviceType||"ev_charging"===t.deviceType?K:W`
                    <label class="toggle-label" title="${this._t("mode_tooltip")}">
                        <span class="dim">${this._t("mode")}</span>
                        <select class="mode-select" data-action="control_mode" data-device="${t.id}">
                            <option value="off" ?selected="${"off"===t.controlMode}">${this._t("off")}</option>
                            <option value="peak_only" ?selected="${"peak_only"===t.controlMode}">${this._t("peak_only")}</option>
                            <option value="surplus" ?selected="${"surplus"===t.controlMode}">${this._t("surplus_mode")}</option>
                        </select>
                    </label>`}
                    <label class="toggle-label" title="${this._t("requires_tooltip")}">
                        <span class="dim">${this._t("requires")}</span>
                        <select class="mode-select" data-action="depends_on" data-device="${t.id}">
                            <option value="" ?selected="${!t.dependsOn.length}">${this._t("action_none")}</option>
                            ${this.devices.filter(e=>e.id!==t.id).map(e=>W`<option value="${e.id}" ?selected="${t.dependsOn.includes(e.id)}">${e.name}</option>`)}
                        </select>
                    </label>
                    <div class="arrows">
                        <button class="arrow-btn" data-action="move-up"   data-device="${t.id}" title="${this._t("move_up")}">&#9650;</button>
                        <button class="arrow-btn" data-action="move-down" data-device="${t.id}" title="${this._t("move_down")}">&#9660;</button>
                    </div>
                </div>
            </div>
        </div>`}async _initSortable(){if(this.devices.length)try{const t=await ke,e=this.renderRoot.getElementById("device-list");if(!e)return;this._sortable&&this._sortable.destroy(),this._sortable=t.create(e,{handle:".drag-handle",filter:".is-child",preventOnFilter:!1,animation:200,easing:"cubic-bezier(0.4, 0, 0.2, 1)",ghostClass:"ghost",chosenClass:"chosen",dragClass:"dragging",forceFallback:!0,fallbackTolerance:3,onStart:()=>{this._interacting=!0},onEnd:t=>{this._interacting=!1,t.oldIndex!==t.newIndex&&(this._applyReorder(),this._regroupChildren(),this.requestUpdate())}})}catch(t){console.warn("SEM: SortableJS not available, drag disabled:",t.message)}}_applyReorder(){const t=this.renderRoot.getElementById("device-list");if(!t)return;const e=Array.from(t.querySelectorAll(".device")).map(t=>t.dataset.id),i={};this.devices.forEach(t=>{i[t.id]=t}),this.devices=e.map((t,e)=>{const s=i[t];return s&&(s.priority=e+1),s}).filter(Boolean),this._sendPriorityUpdate()}_bindEvents(){const t=this.renderRoot,e=t.getElementById("setTargetBtn");e&&!e._semBound&&(e._semBound=!0,e.addEventListener("click",()=>{const e=t.getElementById("targetInput"),i=parseFloat(e?.value);i&&i>0&&i<=20&&(this.targetPeakLimit=i,this._sendTargetPeakUpdate(i),this.requestUpdate())}));const i=t=>{const e=t.target.closest("[data-action]");if(!e)return;const i=e.dataset.action,s=e.dataset.device;if("controllable"===i){const t=this.devices.find(t=>t.id===s);t&&(t.isControllable=!t.isControllable,this._sendDeviceUpdate(s,"controllable",t.isControllable),this.requestUpdate())}else"move-up"===i||"move-down"===i?this._moveDevice(s,"move-up"===i?-1:1):"configure"===i&&this._showConfigureModal(e.dataset.energy,e.dataset.name)},s=t=>{const e=t.target.closest('[data-action="control_mode"]');if(e){const t=e.dataset.device,i=this.devices.find(e=>e.id===t);return void(i&&(i.controlMode=e.value,this._sendDeviceUpdate(t,"control_mode",e.value)))}const i=t.target.closest('[data-action="depends_on"]');if(i){const t=i.dataset.device,e=this.devices.find(e=>e.id===t);if(e){const s=i.value;e.dependsOn=s?[s]:[],this._sendDeviceUpdate(t,"depends_on",s),this._regroupChildren(),this.devices.forEach((t,e)=>{t.priority=e+1}),this.requestUpdate(),this._sendPriorityUpdate()}}},r=t.querySelector("ha-card");r&&!r._semEvtBound&&(r._semEvtBound=!0,r.addEventListener("click",i),r.addEventListener("change",s))}_moveDevice(t,e){const i=this.devices.findIndex(e=>e.id===t);if(-1===i)return;const s=i+e;if(s<0||s>=this.devices.length)return;this.devices[i].dependsOn.length||([this.devices[i],this.devices[s]]=[this.devices[s],this.devices[i]],this._regroupChildren(),this.devices.forEach((t,e)=>{t.priority=e+1}),this.requestUpdate(),this._sendPriorityUpdate())}_getDependencyDepth(t){let e=0,i=t;const s=new Set;for(;i.dependsOn.length>0&&e<5;){s.add(i.id);const t=i.dependsOn[0];if(s.has(t))break;const r=this.devices.find(e=>e.id===t);if(!r)break;e++,i=r}return e}_regroupChildren(){const t=[],e=new Set,i=s=>{e.has(s.id)||(t.push(s),e.add(s.id),this.devices.filter(t=>t.dependsOn.includes(s.id)&&!e.has(t.id)).forEach(t=>i(t)))};this.devices.filter(t=>!t.dependsOn.length).forEach(t=>i(t)),this.devices.forEach(i=>{e.has(i.id)||t.push(i)}),this.devices=t}_sendPriorityUpdate(){this._hass&&this._hass.callService("solar_energy_management","update_device_priorities",{priorities:this.devices.map(t=>({device_id:t.id,priority:t.priority}))})}_sendDeviceUpdate(t,e,i){this._hass&&this._hass.callService("solar_energy_management","update_device_config",{device_id:t,property:e,value:i})}_sendTargetPeakUpdate(t){this._hass&&this._hass.callService("solar_energy_management","update_target_peak",{target_peak_limit:t})}async _ensureEntityPicker(){if(!customElements.get("ha-entity-picker"))try{const t=await(window.loadCardHelpers?.());if(t?.createCardElement){const e=await t.createCardElement({type:"entities",entities:[]});await(e.constructor?.getConfigElement?.())}}catch(t){}}async _showConfigureModal(t,e){const i=this.renderRoot.getElementById("sem-config-modal");i&&i.remove();const s=this.devices.find(e=>e.energySensor===t),r=function(t){const e=t||{};return{type:xe.includes(e.type)?e.type:"switch",entity:e.entity||"",service:e.service||"",param:e.param||"current",shed_value:null!=e.shed_value?e.shed_value:0,restore_value:null!=e.restore_value?e.restore_value:16}}(s?.control),a="manual_mapping"===s?.control?.discovered_via;await this._ensureEntityPicker();const o=document.createElement("div");o.id="sem-config-modal",o.style.cssText="position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:999;display:flex;align-items:center;justify-content:center",o.innerHTML=function({deviceName:t,values:e,t:i,hasManual:s=!1}){const r=e,a="service"===r.type,o=(t,e)=>`<option value="${t}" ${r.type===t?"selected":""}>${e}</option>`;return`\n        <div style="background:var(--card-background-color,#1e1e2e);border-radius:12px;padding:24px;min-width:320px;max-width:90vw;color:var(--primary-text-color,#e0e0e0)">\n            <div style="font-weight:700;margin-bottom:16px">${i("configure_device")}: ${$e(t)}</div>\n            <label style="font-size:13px;opacity:0.7">${i("control_type")}</label>\n            <select id="cfg-type" style="${we}">\n                ${o("switch",i("mode_switch"))}\n                ${o("current",i("mode_current"))}\n                ${o("input_boolean",i("mode_input_boolean"))}\n                ${o("service",i("mode_service"))}\n            </select>\n            <div id="cfg-entity-group" style="display:${a?"none":"block"}">\n                <label style="font-size:13px;opacity:0.7">${i("control_entity")}</label>\n                <input id="cfg-entity" type="text" placeholder="switch.example" value="${$e(r.entity)}" style="${we}">\n            </div>\n            <div id="cfg-service-group" style="display:${a?"block":"none"}">\n                <label style="font-size:13px;opacity:0.7">${i("svc_service")}</label>\n                <input id="cfg-service" type="text" placeholder="keba.set_current" value="${$e(r.service)}" style="${we}">\n                <label style="font-size:13px;opacity:0.7">${i("svc_param")}</label>\n                <input id="cfg-param" type="text" placeholder="current" value="${$e(r.param)}" style="${we}">\n                <div style="display:flex;gap:8px">\n                    <div style="flex:1">\n                        <label style="font-size:13px;opacity:0.7">${i("svc_shed_value")}</label>\n                        <input id="cfg-shed" type="number" value="${$e(r.shed_value)}" style="${we}">\n                    </div>\n                    <div style="flex:1">\n                        <label style="font-size:13px;opacity:0.7">${i("svc_restore_value")}</label>\n                        <input id="cfg-restore" type="number" value="${$e(r.restore_value)}" style="${we}">\n                    </div>\n                </div>\n            </div>\n            <div class="cfg-error" style="color:#f44336;font-size:13px;margin:4px 0 8px;display:none"></div>\n            <div style="display:flex;gap:8px;align-items:center">\n                ${s?`<button id="cfg-remove" style="padding:8px 12px;border-radius:6px;border:none;cursor:pointer;background:transparent;color:#f44336">${i("clear_mapping")}</button>`:""}\n                <div style="flex:1"></div>\n                <button id="cfg-cancel" style="padding:8px 16px;border-radius:6px;border:none;cursor:pointer;background:rgba(255,255,255,0.1);color:inherit">${i("cancel")}</button>\n                <button id="cfg-save" style="padding:8px 16px;border-radius:6px;border:none;cursor:pointer;background:#4caf50;color:white">${i("save")}</button>\n            </div>\n        </div>`}({deviceName:e,values:r,t:t=>this._t(t),hasManual:a}),this.renderRoot.appendChild(o);const n=o.querySelector("#cfg-type"),l=o.querySelector("#cfg-entity-group"),c=o.querySelector("#cfg-service-group"),d=o.querySelector("#cfg-entity"),p=o.querySelector(".cfg-error"),h=t=>{p.textContent=t,p.style.display="block"};let _=null;customElements.get("ha-entity-picker")&&(_=document.createElement("ha-entity-picker"),_.hass=this._hass,_.allowCustomEntity=!0,_.value=d.value,_.includeDomains=be[n.value],_.style.cssText="display:block;margin:6px 0 12px",_.addEventListener("value-changed",t=>{d.value=t.detail.value||""}),d.style.display="none",d.parentNode.insertBefore(_,d));n.addEventListener("change",()=>{const t="service"===n.value;l.style.display=t?"none":"block",c.style.display=t?"block":"none",_&&!t&&(_.includeDomains=be[n.value])}),o.addEventListener("click",t=>{t.target===o&&o.remove()}),o.querySelector("#cfg-cancel").addEventListener("click",()=>o.remove());const g=o.querySelector("#cfg-remove");g&&g.addEventListener("click",()=>{this._hass.callService("solar_energy_management","remove_device_control_mapping",{energy_sensor:t}).then(()=>{s&&(s.control=null,this.requestUpdate()),o.remove()}).catch(t=>h(t.message))}),o.querySelector("#cfg-save").addEventListener("click",()=>{const e=function(t){const e=e=>t.querySelector("#"+e);return{type:e("cfg-type")?.value||"switch",entity:(e("cfg-entity")?.value||"").trim(),service:(e("cfg-service")?.value||"").trim(),param:(e("cfg-param")?.value||"").trim()||"current",shed_value:e("cfg-shed")?.value,restore_value:e("cfg-restore")?.value}}(o);let i;_&&(e.entity=(_.value||"").trim());try{i=function(t,e){const i=xe.includes(e.type)?e.type:"switch";if("service"===i){if(!e.service)throw new Error("mapping_service_required");return{energy_sensor:t,control_type:"service",service:e.service,param:e.param||"current",shed_value:Number(e.shed_value),restore_value:Number(e.restore_value)}}if(!e.entity)throw new Error("mapping_entity_required");return{energy_sensor:t,control_type:i,control_entity:e.entity}}(t,e)}catch(t){return void h(this._t(t.message))}this._hass.callService("solar_energy_management","set_device_control_mapping",i).then(()=>{s&&(s.control="service"===i.control_type?{type:"service",service:i.service,param:i.param,shed_value:i.shed_value,restore_value:i.restore_value,discovered_via:"manual_mapping"}:{type:i.control_type,entity:i.control_entity,discovered_via:"manual_mapping"},this.requestUpdate()),o.remove()}).catch(t=>h(t.message))})}_getPeakColor(){const t=this.targetPeakLimit>0?this.currentPeak/this.targetPeakLimit*100:0;return t>=100?"#f44336":t>=90?"#ff9800":t>=70?"#2196f3":"#4caf50"}_resolveDeviceIcon(t){for(const e of[t.switch_entity,t.power_entity,t.control?.entity])if(e){const t=this._hass?.states[e];if(t?.attributes?.icon)return t.attributes.icon}return{ev_charger:"mdi:ev-station",ev_charging:"mdi:ev-station",heating:"mdi:radiator",heat_pump:"mdi:heat-pump",water_heater:"mdi:water-boiler",hot_water:"mdi:water-boiler",pool_pump:"mdi:pool",appliance:"mdi:washing-machine",climate:"mdi:thermostat",light:"mdi:lightbulb",printer:"mdi:printer",computer:"mdi:desktop-classic",network:"mdi:network",fan:"mdi:fan",dryer:"mdi:tumble-dryer",dishwasher:"mdi:dishwasher",freezer:"mdi:fridge",refrigerator:"mdi:fridge"}[t.device_type]||"mdi:power-plug"}getCardSize(){return Math.max(5,3+this.devices.length)}static getStubConfig(){return{entity_prefix:"sensor.sem_"}}},{type:"sem-load-priority-card",name:"SEM Load Priority Card",description:"Drag and drop interface for managing load shedding priorities",preview:!0});const Se=[{id:"surplus",icon:"mdi:solar-power",color:"#ff9800",titleKey:"surplus_control",subtitleFn:t=>{const e=t._valNum("surplus_active_devices").toFixed(0),i=t._valNum("surplus_total_devices").toFixed(0),s=t._valNum("surplus_allocated_w").toFixed(0);return`${e}/${i} ${t._t("devices")} · ${s}W`}},{id:"battery",icon:"mdi:battery-medium",color:"#4db6ac",titleKey:"battery_management",subtitleFn:t=>{const e=t._valNum("battery_soc").toFixed(0),i=t._val("battery_status")||"";return`SOC ${e}% · ${i?t._t(i.toLowerCase()):"—"}`}},{id:"hotwater",icon:"mdi:water-thermometer",color:"#f06292",titleKey:"hot_water_title",subtitleFn:()=>""},{id:"heatpump",icon:"mdi:heat-pump",color:"#4db6ac",titleKey:"heat_pump_title",subtitleFn:t=>{const e=t._val("heat_pump_sg_ready_state"),i=t._val("heat_pump_mode");return e?`${i||"—"} · ${e}`:""}},{id:"solar",icon:"mdi:solar-panel-large",color:"#ff9800",titleKey:"solar_power_section",subtitleFn:()=>""},{id:"tariff",icon:"mdi:cash-multiple",color:"#96CAEE",titleKey:"tariff_pricing",subtitleFn:t=>{const e=t._val("tariff_provider")||"—",i=t._val("tariff_price_level")||"";return i?`${e} · ${t._t(i.toLowerCase())}`:e}},{id:"peak",icon:"mdi:flash-alert",color:"#ff9800",titleKey:"peak_load_management",subtitleFn:t=>{const e=t._valNum("consecutive_peak_15min").toFixed(1),i=t._valNum("monthly_consecutive_peak").toFixed(1);return`${t._t("peak")} ${e} kW · ${t._t("monthly_peak")} ${i} kW`}},{id:"system",icon:"mdi:cog-outline",color:"#96CAEE",titleKey:"system",subtitleFn:()=>""}],Ce=["sensor.sem_surplus_active_devices","sensor.sem_surplus_total_devices","sensor.sem_surplus_allocated_w","sensor.sem_surplus_total_w","sensor.sem_surplus_distributable_w","sensor.sem_surplus_unallocated_w","number.sem_regulation_offset","sensor.sem_battery_soc","sensor.sem_battery_status","number.sem_battery_priority_soc","number.sem_battery_minimum_soc","number.sem_battery_resume_soc","sensor.sem_diag_battery_capacity","number.sem_hot_water_solar_target","number.sem_legionella_target_temp","binary_sensor.sem_heat_pump_registered","sensor.sem_heat_pump_sg_ready_state","sensor.sem_heat_pump_mode","binary_sensor.sem_heat_pump_solar_boost","number.sem_heat_pump_boost_offset","number.sem_minimum_solar_power","number.sem_maximum_grid_import","sensor.sem_tariff_provider","sensor.sem_tariff_price_level","sensor.sem_tariff_current_import_rate","number.sem_cheap_price_threshold","number.sem_expensive_price_threshold","sensor.sem_consecutive_peak_15min","sensor.sem_monthly_consecutive_peak","sensor.sem_current_vs_peak_percentage","sensor.sem_load_management_status","sensor.sem_load_management_recommendation","sensor.sem_peak_margin","sensor.sem_available_load_reduction","sensor.sem_controllable_devices_count","switch.sem_observer_mode"];yt("sem-control-card",class extends xt{static get watchedEntities(){return Ce}static get properties(){return{...super.properties,_showHelp:{state:!0}}}constructor(){super(),this._collapsed={ev:!1,surplus:!0,battery:!1,hotwater:!0,heatpump:!0,solar:!0,tariff:!1,peak:!0,system:!0},this._showHelp=!1}_toggleHelp(){this._showHelp=!this._showHelp}setConfig(t){super.setConfig(t),this._prefix=t.entity_prefix||"sensor.sem_"}_val(t){const e=this._hass?.states[`${this._prefix}${t}`];return e&&"unavailable"!==e.state&&"unknown"!==e.state?e.state:""}_valNum(t,e=0){const i=this._hass?.states[`${this._prefix}${t}`];return i&&"unavailable"!==i.state&&"unknown"!==i.state?parseFloat(i.state)??e:e}_numVal(t,e=0){const i=this._hass?.states[`number.sem_${t}`];return i&&"unavailable"!==i.state&&"unknown"!==i.state?parseFloat(i.state)??e:e}_switchOn(t){return"on"===this._hass?.states[`switch.sem_${t}`]?.state}_toggleSection(t){this._collapsed={...this._collapsed,[t]:!this._collapsed[t]},this.requestUpdate()}_renderToggle(t,e,i){const s="on"===this._hass?.states[t]?.state;return W`
            <div class="toggle-row">
                <span class="toggle-label">${this._t(e)}</span>
                <div class="toggle-track ${s?"on":""}" @click=${()=>this._toggleSwitch(t)}>
                    <div class="toggle-thumb"></div>
                </div>
            </div>
        `}_renderStepper(t,e,i,s){const r=this._hass?.states[t];if(!r)return K;const a=this._frozenEntities[t],o=a?a.value:parseFloat(r.state)||0,n=parseFloat(r.attributes.step)||1,l=r.attributes.unit_of_measurement||"",c=n<1?1:0,d=o.toFixed(c)+(l?" "+l:"");return W`
            <div class="stepper-cell">
                <div class="stepper-row">
                    <span class="stepper-label">${this._t(e)}</span>
                    <div class="stepper-controls">
                        <button
                            class="stepper-minus" aria-label="Decrease"
                            @click=${()=>this._stepNumber(t,-1)}
                            @pointerdown=${()=>this._startHold(t,-1)}
                            @pointerup=${()=>this._stopHold(t)}
                            @pointerleave=${()=>this._stopHold(t)}
                        >−</button>
                        <span class="stepper-value">${d}</span>
                        <button
                            class="stepper-plus" aria-label="Increase"
                            @click=${()=>this._stepNumber(t,1)}
                            @pointerdown=${()=>this._startHold(t,1)}
                            @pointerup=${()=>this._stopHold(t)}
                            @pointerleave=${()=>this._stopHold(t)}
                        >+</button>
                    </div>
                </div>
                ${this._showHelp&&s?W`<div class="setting-help-text">${this._t(s)}</div>`:K}
            </div>
        `}_renderSelect(t,e,i){const s=this._hass?.states[t];if(!s)return K;const r=this._frozenEntities[t],a=r?r.value:s.state,o=s.attributes.options||[];return W`
            <div class="ctrl-row">
                <span class="ctrl-label">${this._t(e)}</span>
                <select
                    class="sem-select"
                    .value=${a}
                    @change=${e=>this._selectOption(t,e.target.value)}
                >
                    ${o.map(t=>W`<option value="${t}" ?selected=${t===a}>${t}</option>`)}
                </select>
            </div>
        `}_renderSurplusSection(t){const e=this._valNum("surplus_total_w").toFixed(0),i=this._valNum("surplus_distributable_w").toFixed(0),s=this._valNum("surplus_allocated_w").toFixed(0),r=this._valNum("surplus_unallocated_w").toFixed(0);return W`
            <div class="info-tiles">
                <div class="info-tile">
                    <ha-icon icon="mdi:solar-power" style="--mdc-icon-size:18px;color:#ff9800"></ha-icon>
                    <div class="info-tile-content">
                        <span class="info-tile-label">${this._t("surplus_available")}</span>
                        <span class="info-tile-values">
                            <span>${e}W</span>
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
            ${this._renderStepper("number.sem_regulation_offset","regulation_offset",t)}
        `}_renderBatterySection(t){const e=this._valNum("diag_battery_capacity"),i=e>0?e.toFixed(1)+" kWh":"—";return W`
            <div class="stepper-pair">
                ${this._renderStepper("number.sem_battery_priority_soc","priority_soc",t,"setting_help_priority_soc")}
                ${this._renderStepper("number.sem_battery_minimum_soc","minimum_soc",t,"setting_help_minimum_soc")}
            </div>
            <div class="stepper-pair">
                ${this._renderStepper("number.sem_battery_resume_soc","resume_soc",t,"setting_help_resume_soc")}
                <div class="readonly-row">
                    <span class="ctrl-label">${this._t("capacity_kwh")}</span>
                    <span class="readonly-value">${i}</span>
                </div>
            </div>
        `}_renderHeatPumpSection(t){const e=this._val("heat_pump_registered");if(!(!0===e||"True"===e||"on"===e))return W`<div class="info-box-text" style="opacity:0.6">
                ${this._t("heat_pump_not_configured")}
            </div>`;const i=this._val("heat_pump_sg_ready_state"),s=this._val("heat_pump_mode")||"—",r=this._switchOn("heat_pump_solar_boost")?"#ff9800":"#4db6ac";return W`
            <div class="readonly-row">
                <ha-icon icon="mdi:heat-pump-outline" style="--mdc-icon-size:18px;color:${r}"></ha-icon>
                <span class="ctrl-label" style="flex:1">${this._t("heat_pump_mode")}</span>
                <span class="readonly-value">${this._t(s.toLowerCase())||s}</span>
            </div>
            <div class="readonly-row">
                <ha-icon icon="mdi:transmission-tower" style="--mdc-icon-size:18px;color:${r}"></ha-icon>
                <span class="ctrl-label" style="flex:1">${this._t("heat_pump_sg_ready_state")}</span>
                <span class="readonly-value">${i}</span>
            </div>
            ${this._renderStepper("number.sem_heat_pump_boost_offset","heat_pump_boost_offset",t)}
        `}_renderHotWaterSection(t){return W`
            <div class="stepper-pair">
                ${this._renderStepper("number.sem_hot_water_solar_target","solar_boost_target",t)}
                ${this._renderStepper("number.sem_legionella_target_temp","legionella_target",t)}
            </div>
            <div class="info-box">
                <ha-icon icon="mdi:shield-alert" style="--mdc-icon-size:16px;color:#ff9800"></ha-icon>
                <div>
                    <div class="info-box-title">${this._t("legionella_prevention")}</div>
                    <div class="info-box-text">
                        DE (DVGW W 551): ≥ 60°C · CH (SIA 385/1): ≥ 60°C · AT (ÖNORM B 5019): 60°C / 70°C 3 min
                    </div>
                </div>
            </div>
        `}_renderSolarSection(t){return W`
            <div class="stepper-pair">
                ${this._renderStepper("number.sem_minimum_solar_power","min_solar",t)}
                ${this._renderStepper("number.sem_maximum_grid_import","max_grid_import",t)}
            </div>
        `}_renderTariffSection(t){const e=this._hass?.states["sensor.sem_tariff_current_import_rate"],i=e?e.state:"—",s=e?.attributes?.unit_of_measurement||"";return W`
            <div class="readonly-row tariff-rate-row">
                <ha-icon icon="mdi:flash" style="--mdc-icon-size:18px;color:#ff9800"></ha-icon>
                <span class="ctrl-label" style="flex:1">${this._t("current_electricity_price")}</span>
                <span class="readonly-value tariff-rate-value">${i} ${s}</span>
            </div>
            <div class="stepper-pair">
                ${this._renderStepper("number.sem_cheap_price_threshold","cheap_threshold",t,"setting_help_cheap_threshold")}
                ${this._renderStepper("number.sem_expensive_price_threshold","expensive_threshold",t,"setting_help_expensive_threshold")}
            </div>
        `}_renderPeakSection(t){const e=this._valNum("current_vs_peak_percentage"),i=e>90?"#f44336":e>70?"#ff9800":"#8DC892",s=this._valNum("controllable_devices_count").toFixed(0),r=this._valNum("available_load_reduction");return W`
            <div class="peak-hero">
                <span class="peak-pct" style="color:${i}">${e.toFixed(0)}%</span>
                <span class="peak-of-limit">${this._t("of_limit")}</span>
            </div>
            <div class="peak-detail">
                <span class="peak-status">${(()=>{const t=this._val("load_management_status");return t?this._t(t):"—"})()}</span>
                <span class="peak-sep">·</span>
                <span class="peak-rec">${(()=>{const t=this._val("load_management_recommendation");return t?this._t(t):""})()}</span>
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
        `}_renderSystemSection(t){return W`
            <div class="toggle-group">
                ${this._renderToggle("switch.sem_observer_mode","observer_mode",t)}
            </div>
        `}_renderSectionHeader(t,e){const i=this._collapsed[t.id],s=i?"rotate(-90deg)":"rotate(0deg)";return W`
            <div
                class="section-header"
                tabindex="0"
                role="button"
                aria-expanded="${!i}"
                @click=${()=>this._toggleSection(t.id)}
                @keydown=${e=>{"Enter"!==e.key&&" "!==e.key||(e.preventDefault(),this._toggleSection(t.id))}}
            >
                <ha-icon icon="${t.icon}" style="--mdc-icon-size:20px;color:${t.color}"></ha-icon>
                <span class="section-title-text">${this._t(t.titleKey)}</span>
                <span class="section-subtitle">${t.subtitleFn(this)}</span>
                <ha-icon
                    class="chevron"
                    icon="mdi:chevron-down"
                    style="--mdc-icon-size:18px;transform:${s}"
                ></ha-icon>
            </div>
        `}_renderSection(t,e,i){const s=this._collapsed[t.id];return W`
            <div class="section ${s?"":"expanded"}"
                 style="--section-accent: ${t.color}">
                ${this._renderSectionHeader(t,i)}
                <div class="section-content ${s?"":"expanded"}">
                    <div class="section-body">
                        ${e(i)}
                    </div>
                </div>
            </div>
        `}render(){if(!this._config)return K;const t=this._theme(),e=!1!==t.isDark,i=t.accent||"#42a5f5",s=this._switchOn("observer_mode"),r={surplus:t=>this._renderSurplusSection(t),battery:t=>this._renderBatterySection(t),hotwater:t=>this._renderHotWaterSection(t),heatpump:t=>this._renderHeatPumpSection(t),solar:t=>this._renderSolarSection(t),tariff:t=>this._renderTariffSection(t),peak:t=>this._renderPeakSection(t),system:t=>this._renderSystemSection(t)};return W`
            <style>
                :host { display: block; contain: layout style paint; }
                .wrap {
                    padding: 16px;
                    position: relative;
                    background:
                        radial-gradient(ellipse 70% 60% at 50% 25%, rgba(150,202,238,0.06) 0%, transparent 100%),
                        radial-gradient(circle at 2px 2px, ${t.dotColor} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${t.text});
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
                    background: ${t.surface};
                    border: 1px solid ${t.surfaceBorder};
                    overflow: hidden;
                    transition: border-color 0.2s, box-shadow 0.2s;
                    position: relative;
                }
                /* When expanded: subtle color-coded accent stripe matching the
                   section icon's color, plus a soft glow that ties the card
                   together with the EV card's hint-row aesthetic. */
                .section.expanded {
                    border-color: color-mix(in srgb, var(--section-accent) 40%, ${t.surfaceBorder});
                    box-shadow: inset 3px 0 0 0 var(--section-accent);
                }
                .section:hover { border-color: ${e?"rgba(255,255,255,0.18)":"rgba(0,0,0,0.12)"}; }

                .section-header {
                    display: flex; align-items: center; gap: 10px;
                    padding: 13px 14px;
                    cursor: pointer;
                    user-select: none;
                    -webkit-user-select: none;
                    transition: background 0.15s;
                }
                .section-header:hover { background: ${t.surfaceHover}; }
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
                    color: var(--secondary-text-color, ${t.textSec});
                    text-align: right;
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    margin-right: 4px;
                }
                .chevron {
                    transition: transform 0.25s ease;
                    color: var(--secondary-text-color, ${t.textSec});
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

                /* ── Card-level help toggle (2026-06-06). Tap (?) to reveal
                   inline one-line setting explanations across all sections
                   that opt in (Battery, Tariff). ── */
                .card-help-bar {
                    display: flex; justify-content: flex-end;
                    margin: -4px 0 6px;
                }
                .help-toggle {
                    cursor: pointer;
                    color: var(--secondary-text-color, ${t.textSec});
                    opacity: 0.6;
                    flex-shrink: 0;
                    transition: opacity 0.15s, color 0.15s;
                    user-select: none;
                    -webkit-user-select: none;
                    padding: 4px;
                    border-radius: 50%;
                }
                .help-toggle:hover { opacity: 1; }
                .help-toggle.on { color: ${i}; opacity: 1; }
                .stepper-cell { display: flex; flex-direction: column; }
                .setting-help-text {
                    font-size: 11px;
                    line-height: 1.35;
                    color: var(--secondary-text-color, ${t.textSec});
                    opacity: 0.75;
                    padding: 2px 4px 6px 0;
                    margin-top: -4px;
                    font-style: italic;
                }

                /* ── Toggle ── */
                .toggle-group {
                    border-bottom: 1px solid ${t.surfaceBorder};
                    margin-bottom: 8px;
                    padding-bottom: 4px;
                }
                .toggle-row {
                    display: flex; align-items: center; justify-content: space-between;
                    padding: 8px 0;
                }
                .toggle-label { font-size: 14px; font-weight: 500; }
                .toggle-track {
                    position: relative;
                    width: 42px; height: 24px;
                    border-radius: 12px;
                    background: ${e?"rgba(255,255,255,0.15)":"rgba(0,0,0,0.18)"};
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

                /* ── Select ── */
                .ctrl-row {
                    display: flex; align-items: center; justify-content: space-between;
                    padding: 8px 0;
                    border-bottom: 1px solid ${t.surfaceBorder};
                    margin-bottom: 4px;
                }
                .ctrl-label { font-size: 14px; font-weight: 500; }
                .sem-select {
                    background: ${t.surface};
                    border: 1px solid ${t.surfaceBorder};
                    border-radius: 8px;
                    color: var(--primary-text-color, ${t.text});
                    padding: 6px 10px;
                    font-size: 14px;
                    font-family: inherit;
                    cursor: pointer;
                    min-width: 120px;
                    outline: none;
                }
                .sem-select:focus { border-color: ${i}; }
                .sem-select option {
                    background: ${e?"#1e232d":"#fff"};
                    color: ${e?"#e0e0e0":"#333"};
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
                    border: 1px solid ${t.surfaceBorder};
                    background: ${t.surface};
                    color: var(--primary-text-color, ${t.text});
                    font-size: 16px; font-weight: 600;
                    cursor: pointer;
                    display: flex; align-items: center; justify-content: center;
                    transition: background 0.15s, border-color 0.15s;
                    user-select: none; -webkit-user-select: none;
                    touch-action: manipulation;
                    padding: 0; line-height: 1;
                }
                .stepper-minus:hover, .stepper-plus:hover {
                    background: ${t.surfaceHover};
                    border-color: ${i};
                }
                .stepper-minus:active, .stepper-plus:active {
                    background: ${e?"rgba(255,255,255,0.15)":"rgba(0,0,0,0.08)"};
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
                    color: var(--secondary-text-color, ${t.textSec});
                }
                .tariff-rate-row {
                    gap: 8px;
                    border-bottom: 1px solid ${t.surfaceBorder};
                    margin-bottom: 8px; padding-bottom: 10px;
                }
                .tariff-rate-value { font-size: 15px; font-weight: 700; color: ${t.text}; }

                /* ── Info tiles (surplus, peak) ── */
                .info-tiles {
                    display: grid; grid-template-columns: 1fr 1fr;
                    gap: 8px; margin: 8px 0;
                }
                .info-tile {
                    display: flex; align-items: flex-start; gap: 8px;
                    padding: 10px; border-radius: 10px;
                    background: ${e?"rgba(255,255,255,0.03)":"rgba(0,0,0,0.02)"};
                    border: 1px solid ${t.surfaceBorder};
                }
                .info-tile ha-icon { margin-top: 1px; flex-shrink: 0; }
                .info-tile-content { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
                .info-tile-label {
                    font-size: 11px; font-weight: 500; text-transform: uppercase;
                    color: var(--secondary-text-color, ${t.textSec});
                    letter-spacing: 0.3px;
                }
                .info-tile-values { font-size: 13px; font-weight: 600; display: flex; gap: 4px; flex-wrap: wrap; }
                .info-tile-value { font-size: 13px; font-weight: 600; }
                .info-tile-sep { color: var(--secondary-text-color, ${t.textSec}); }
                @media (max-width: 480px) { .info-tiles { grid-template-columns: 1fr; } }

                /* ── Info box (legionella) ── */
                .info-box {
                    display: flex; gap: 8px;
                    padding: 10px 12px; border-radius: 10px;
                    background: ${e?"rgba(255,152,0,0.06)":"rgba(255,152,0,0.05)"};
                    border: 1px solid rgba(255,152,0,0.2);
                    margin-top: 8px;
                }
                .info-box ha-icon { flex-shrink: 0; margin-top: 1px; }
                .info-box-title { font-size: 12px; font-weight: 600; margin-bottom: 2px; }
                .info-box-text {
                    font-size: 11px; line-height: 1.4;
                    color: var(--secondary-text-color, ${t.textSec});
                }

                /* ── Peak hero ── */
                .peak-hero {
                    display: flex; align-items: baseline; justify-content: center;
                    gap: 6px; padding: 4px 0;
                }
                .peak-pct { font-size: 28px; font-weight: 700; font-variant-numeric: tabular-nums; }
                .peak-of-limit {
                    font-size: 12px; font-weight: 500;
                    color: var(--secondary-text-color, ${t.textSec});
                    text-transform: uppercase;
                }
                .peak-detail {
                    text-align: center; padding: 0 0 8px;
                    font-size: 12px;
                    color: var(--secondary-text-color, ${t.textSec});
                }
                .peak-sep { margin: 0 4px; }
            </style>
            <div class="wrap">
                <div class="observer-warning">
                    <ha-icon icon="mdi:eye-outline" style="--mdc-icon-size:20px;color:#f44336"></ha-icon>
                    <span>${this._t("observer_mode_active")} — ${this._t("observer_mode_readonly")}</span>
                </div>
                <div class="card-help-bar">
                    <ha-icon
                        class="help-toggle ${this._showHelp?"on":""}"
                        icon="${this._showHelp?"mdi:help-circle":"mdi:help-circle-outline"}"
                        title="${this._t("zone_help_toggle")}"
                        @click=${()=>this._toggleHelp()}
                        style="--mdc-icon-size:18px"
                    ></ha-icon>
                </div>
                ${Se.map(e=>this._renderSection(e,r[e.id],t))}
            </div>
        `}getCardSize(){return 12}static getStubConfig(){return{entity_prefix:"sensor.sem_"}}},{type:"custom:sem-control-card",name:"SEM Control Card",description:"Consolidated control panel for Solar Energy Management",preview:!1});class Ee extends lt{static get properties(){return{hass:{type:Object},entryId:{type:String,attribute:"entry-id"},optionKey:{type:String,attribute:"option-key"},chargerIndex:{type:Number,attribute:"charger-index"},chargerKey:{type:String,attribute:"charger-key"},domain:{type:String},includeDeviceClass:{type:String,attribute:"include-device-class"},label:{type:String},_saving:{state:!0},_error:{state:!0}}}constructor(){super(),this.entryId="",this.optionKey="",this.chargerIndex=-1,this.chargerKey="",this.domain="",this.includeDeviceClass="",this.label="",this._saving=!1,this._error=""}static get styles(){return a`
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
        `}_entry(){return this.hass&&this.entryId&&(this.hass.config_entries||[]).find(t=>t.entry_id===this.entryId)||null}_currentValue(){const t=this._entry();if(!t||!t.options)return"";if(this.chargerKey&&this.chargerIndex>=0){const e=t.options.ev_chargers||[];return e[this.chargerIndex]?.[this.chargerKey]||""}return t.options[this.optionKey]||""}async _onChange(t){const e=t.detail?.value||"",i=this._entry();if(!i)return void(this._error="config entry not found");let s;if(this._saving=!0,this._error="",this.chargerKey&&this.chargerIndex>=0){const t=(i.options?.ev_chargers||[]).map(t=>({...t}));t[this.chargerIndex]||(t[this.chargerIndex]={}),t[this.chargerIndex][this.chargerKey]=e,s={...i.options,ev_chargers:t}}else s={...i.options,[this.optionKey]:e};try{await this.hass.callWS({type:"config_entries/update",entry_id:this.entryId,options:s}),this._saving=!1}catch(t){this._saving=!1,this._error=t?.message||String(t),console.error("[sem-entity-picker] save failed",t)}}render(){if(!this.hass)return K;const t=this._currentValue();return this.domain&&this.domain,this.includeDeviceClass&&this.includeDeviceClass,W`
            <div class="picker-row">
                ${this.label?W`<span class="picker-label">${this.label}</span>`:K}
                <ha-entity-picker
                    .hass=${this.hass}
                    .value=${t}
                    .includeDomains=${this.domain?[this.domain]:void 0}
                    .includeDeviceClasses=${this.includeDeviceClass?[this.includeDeviceClass]:void 0}
                    .allowCustomEntity=${!1}
                    @value-changed=${this._onChange}>
                </ha-entity-picker>
            </div>
            ${this._error?W`<div class="status error">⚠ ${this._error}</div>`:this._saving?W`<div class="status">saving…</div>`:K}
        `}}customElements.get("sem-entity-picker")||customElements.define("sem-entity-picker",Ee);const ze=[{id:"overview",icon:"mdi:check-decagram",color:"#8DC892",titleKey:"config_section_overview",subtitleFn:t=>t._overviewSubtitle(),expanded:!0},{id:"ev_chargers",icon:"mdi:ev-station",color:"#5BC8D8",titleKey:"config_section_ev_chargers",subtitleFn:t=>t._evChargersSubtitle()},{id:"battery_zones",icon:"mdi:battery-charging-medium",color:"#4db6ac",titleKey:"config_section_battery_zones",subtitleFn:t=>t._batteryZonesSubtitle()},{id:"tariff",icon:"mdi:cash-multiple",color:"#96CAEE",titleKey:"config_section_tariff",subtitleFn:t=>t._tariffSubtitle()},{id:"heat_pump",icon:"mdi:heat-pump",color:"#4db6ac",titleKey:"config_section_heat_pump",subtitleFn:t=>t._heatPumpSubtitle()},{id:"battery_scheduler",icon:"mdi:calendar-clock",color:"#f06292",titleKey:"config_section_battery_scheduler",subtitleFn:()=>""},{id:"load_management",icon:"mdi:flash-alert",color:"#ff9800",titleKey:"config_section_load_management",subtitleFn:t=>t._loadMgmtSubtitle()},{id:"forecast",icon:"mdi:weather-partly-cloudy",color:"#ff9800",titleKey:"config_section_forecast",subtitleFn:t=>t._forecastSubtitle()},{id:"notifications",icon:"mdi:bell-outline",color:"#96CAEE",titleKey:"config_section_notifications",subtitleFn:()=>""},{id:"advanced",icon:"mdi:cog-outline",color:"#888",titleKey:"config_section_advanced",subtitleFn:()=>""}],Me=["binary_sensor.sem_heat_pump_registered","sensor.sem_heat_pump_mode","sensor.sem_heat_pump_sg_ready_state","number.sem_heat_pump_boost_offset","sensor.sem_tariff_provider","sensor.sem_tariff_price_level","sensor.sem_tariff_current_import_rate","sensor.sem_forecast_source","sensor.sem_load_management_status","sensor.sem_battery_soc","sensor.sem_battery_status","number.sem_battery_priority_soc","number.sem_battery_buffer_soc","number.sem_battery_auto_start_soc","number.sem_battery_assist_floor_soc","number.sem_battery_minimum_soc","number.sem_battery_resume_soc","number.sem_cheap_price_threshold","number.sem_expensive_price_threshold","number.sem_minimum_solar_power","number.sem_maximum_grid_import","number.sem_update_interval","number.sem_power_delta","number.sem_current_delta","number.sem_soc_delta","switch.sem_observer_mode"];yt("sem-config-card",class extends xt{static get watchedEntities(){return Me}static get properties(){return{...super.properties,_showHelp:{state:!0},_entryId:{state:!0},_saveStatus:{state:!0}}}constructor(){super(),this._collapsed={overview:!1,ev_chargers:!0,battery_zones:!0,tariff:!0,heat_pump:!0,battery_scheduler:!0,load_management:!0,forecast:!0,notifications:!0,advanced:!0},this._showHelp=!1,this._entryId="",this._saveStatus={}}setConfig(t){super.setConfig(t),this._prefix=t.entity_prefix||"sensor.sem_",t.entry_id&&(this._entryId=t.entry_id)}async _ensureEntryId(){if(this._entryId||!this._hass)return this._entryId;try{const t=await this._hass.callWS({type:"config_entries/get",domain:"solar_energy_management"});Array.isArray(t)&&t.length>0&&(this._entryId=t[0].entry_id,this.requestUpdate())}catch(t){console.warn("[sem-config-card] entry lookup failed",t)}return this._entryId}async _saveOption(t,e,i){const s=await this._ensureEntryId();this._saveStatus={...this._saveStatus,[i||t]:"saving"};try{await this._hass.callService("solar_energy_management","set_option",{options:{[t]:e},...s?{entry_id:s}:{}}),this._saveStatus={...this._saveStatus,[i||t]:"ok"},this._options={...this._options,[t]:e},this.requestUpdate(),setTimeout(()=>{this._saveStatus={...this._saveStatus},delete this._saveStatus[i||t],this.requestUpdate()},1200)}catch(e){console.error("[sem-config-card] save failed",t,e),this._saveStatus={...this._saveStatus,[i||t]:e?.message||"save failed"},this.requestUpdate()}}_options={};async _refreshOptions(){if(this._hass)try{const t=await this._hass.callService("solar_energy_management","get_config",{},void 0,void 0,!0),e=t?.response?.config||{};this._options=e,t?.response?.entry_id&&!this._entryId&&(this._entryId=t.response.entry_id),this.requestUpdate()}catch(t){console.warn("[sem-config-card] get_config failed",t)}}connectedCallback(){super.connectedCallback(),this._hass?this._ensureEntryId().then(()=>this._refreshOptions()):this._needsEntryLookup=!0}set hass(t){super.hass=t,this._needsEntryLookup&&t&&(this._needsEntryLookup=!1,this._ensureEntryId().then(()=>this._refreshOptions()))}get hass(){return super.hass}_toggleHelp(){this._showHelp=!this._showHelp}_toggleSection(t){this._collapsed={...this._collapsed,[t]:!this._collapsed[t]},this.requestUpdate()}_val(t){const e=this._hass?.states[`${this._prefix}${t}`];return e&&"unavailable"!==e.state&&"unknown"!==e.state?e.state:""}_valNum(t,e=0){const i=this._hass?.states[`${this._prefix}${t}`];if(!i||"unavailable"===i.state||"unknown"===i.state)return e;const s=parseFloat(i.state);return Number.isNaN(s)?e:s}_switchOn(t){const e=this._hass?.states[`switch.sem_${t}`];return"on"===e?.state}async _toggleSwitch(t){const e=this._hass?.states[t];e&&await this._hass.callService("switch","on"===e.state?"turn_off":"turn_on",{entity_id:t})}async _stepNumber(t,e){const i=this._hass?.states[t];if(!i)return;const s=parseFloat(i.attributes.step)||1,r=parseFloat(i.attributes.min)??0,a=parseFloat(i.attributes.max)??100;let o=(parseFloat(i.state)||0)+e*s;o=Math.max(r,Math.min(a,o)),await this._hass.callService("number","set_value",{entity_id:t,value:o})}async _selectOption(t,e){await this._hass.callService("select","select_option",{entity_id:t,option:e})}_overviewSubtitle(){const t=this._chargersList().length,e="on"===this._val("heat_pump_registered"),i=[];return i.push(`${t} ${this._t("config_subtitle_chargers")}`),e&&i.push(this._t("config_subtitle_heatpump_on")),i.join(" · ")}_evChargersSubtitle(){return`${this._chargersList().length}`}_batteryZonesSubtitle(){const t=this._valNum("battery_soc");return`${this._t("soc")} ${t.toFixed(0)}%`}_tariffSubtitle(){const t=this._val("tariff_provider")||"—",e=this._val("tariff_price_level")||"";return e?`${t} · ${this._t(e.toLowerCase())||e}`:t}_heatPumpSubtitle(){return"on"===this._val("heat_pump_registered")?this._t("configured"):this._t("not_configured")}_loadMgmtSubtitle(){return this._val("load_management_status")||""}_forecastSubtitle(){const t=this._val("forecast_source")||"";return t||this._t("not_configured")}_chargersList(){const t=new Set;for(const e of Object.keys(this._hass?.states||{})){const i=e.match(/^number\.sem_charger_(.+)_minimum_current$/);i&&t.add(i[1])}return Array.from(t).sort()}_openHaSettings(t=""){window.history.pushState(null,"","/config/integrations/integration/solar_energy_management"),window.dispatchEvent(new PopStateEvent("popstate"))}_renderStepper(t,e,i,s){const r=this._hass?.states[t];if(!r)return K;const a=parseFloat(r.state)||0,o=parseFloat(r.attributes.step)||1,n=r.attributes.unit_of_measurement||"",l=o<1?1:0,c=a.toFixed(l)+(n?" "+n:"");return W`
            <div class="stepper-cell">
                <div class="stepper-row">
                    <span class="stepper-label">${this._t(e)}</span>
                    <div class="stepper-controls">
                        <button class="stepper-minus" @click=${()=>this._stepNumber(t,-1)}>−</button>
                        <span class="stepper-value">${c}</span>
                        <button class="stepper-plus" @click=${()=>this._stepNumber(t,1)}>+</button>
                    </div>
                </div>
                ${this._showHelp&&s?W`<div class="setting-help-text">${this._t(s)}</div>`:K}
            </div>
        `}_renderToggle(t,e,i,s){const r=this._hass?.states[t];if(!r)return K;const a="on"===r.state;return W`
            <div class="stepper-cell">
                <div class="toggle-row">
                    <span class="toggle-label">${this._t(e)}</span>
                    <div class="toggle-track ${a?"on":""}" @click=${()=>this._toggleSwitch(t)}>
                        <div class="toggle-thumb"></div>
                    </div>
                </div>
                ${this._showHelp&&s?W`<div class="setting-help-text">${this._t(s)}</div>`:K}
            </div>
        `}_renderSelect(t,e,i,s){const r=this._hass?.states[t];if(!r)return K;const a=r.state,o=r.attributes.options||[];return W`
            <div class="stepper-cell">
                <div class="ctrl-row">
                    <span class="ctrl-label">${this._t(e)}</span>
                    <select class="sem-select" .value=${a}
                            @change=${e=>this._selectOption(t,e.target.value)}>
                        ${o.map(t=>W`<option value="${t}" ?selected=${t===a}>${this._t(t.toLowerCase())||t}</option>`)}
                    </select>
                </div>
                ${this._showHelp&&s?W`<div class="setting-help-text">${this._t(s)}</div>`:K}
            </div>
        `}_renderHaSettingsButton(t){return W`
            <button class="ha-settings-btn" @click=${()=>this._openHaSettings()}>
                <ha-icon icon="mdi:cog-outline" style="--mdc-icon-size:14px"></ha-icon>
                ${this._t(t)}
            </button>
        `}_renderOverview(t){const e=!!this._hass?.states["sensor.sem_charging_state"],i=this._chargersList().length,s="on"===this._val("heat_pump_registered");return W`
            <div class="overview-grid">
                <div class="overview-item">
                    <ha-icon icon="mdi:flash" style="color:#ff9800"></ha-icon>
                    <span>${this._t("config_overview_energy_dashboard")}</span>
                    <span class="overview-status ${e?"ok":"warn"}">${e?"✓":"!"}</span>
                </div>
                <div class="overview-item">
                    <ha-icon icon="mdi:ev-station" style="color:#5BC8D8"></ha-icon>
                    <span>${this._t("config_overview_chargers")}: ${i}</span>
                </div>
                <div class="overview-item">
                    <ha-icon icon="mdi:heat-pump" style="color:#4db6ac"></ha-icon>
                    <span>${this._t("heat_pump_title")}: ${s?this._t("configured"):this._t("not_configured")}</span>
                </div>
            </div>
            <div class="overview-help">${this._t("config_overview_help")}</div>
            <div class="overview-actions">
                ${this._renderHaSettingsButton("config_open_ha_settings")}
            </div>
        `}_renderEvChargers(t){const e=this._options||{},i=e.ev_chargers||[],s=this._chargersList();if(0===i.length&&0===s.length)return W`
                <div class="empty-state">
                    <ha-icon icon="mdi:ev-station-outline" style="--mdc-icon-size:32px;color:#5BC8D8;opacity:0.7"></ha-icon>
                    <div class="empty-title">${this._t("config_ev_no_chargers")}</div>
                    <div class="empty-help">${this._t("config_ev_add_via_settings")}</div>
                    ${this._renderHaSettingsButton("config_ev_add_button")}
                </div>
            `;const r=i.length?i:s.map(t=>({}));return W`
            ${r.map((i,r)=>{const a=i.id||s[r];return W`
                <div class="charger-block">
                    <div class="charger-block-title">
                        <ha-icon icon="mdi:ev-station" style="--mdc-icon-size:18px;color:#5BC8D8"></ha-icon>
                        ${this._chargerFriendlyName(a)}
                    </div>
                    ${this._renderPickerNested(r,"ev_connected_sensor","config_ev_connected_sensor","binary_sensor",null,e,"config_help_ev_connected_sensor")}
                    ${this._renderPickerNested(r,"ev_charging_power_sensor","config_ev_charging_power","sensor","power",e,"config_help_ev_charging_power")}
                    ${this._renderPickerNested(r,"ev_current_control_entity","config_ev_current_control","number",null,e,"config_help_ev_current_control")}
                    ${this._renderPickerNested(r,"vehicle_soc_entity","config_ev_vehicle_soc","sensor",null,e,"config_help_ev_vehicle_soc")}
                    ${this._renderTargetTypeSelectNested(r,i,e)}
                    <div class="stepper-pair">
                        ${this._renderStepper(`number.sem_charger_${a}_minimum_current`,"minimum_soc",t,"tile_help_min_amps")}
                        ${this._renderStepper(`number.sem_charger_${a}_vehicle_min_current`,"vehicle_min_current",t,"tile_help_vehicle_min_amps")}
                    </div>
                    <div class="stepper-pair">
                        ${this._renderStepper(`number.sem_charger_${a}_initial_current`,"initial_current",t,"tile_help_start_amps")}
                        ${this._renderStepper(`number.sem_charger_${a}_ev_battery_capacity_kwh`,"capacity_kwh",t,"tile_help_capacity")}
                    </div>
                </div>
            `})}
            <div class="section-footer">
                ${this._renderHaSettingsButton("config_ev_add_remove")}
            </div>
        `}_chargerFriendlyName(t){return(this._hass?.states[`number.sem_charger_${t}_minimum_current`]?.attributes?.friendly_name||t).replace(/\s+Min Amps$/i,"")}_renderBatteryZones(t){return W`
            <div class="stepper-pair">
                ${this._renderStepper("number.sem_battery_auto_start_soc","auto_start_soc",t,"zone_help_autostart")}
                ${this._renderStepper("number.sem_battery_buffer_soc","buffer_soc",t,"zone_help_buffer")}
            </div>
            <div class="stepper-pair">
                ${this._renderStepper("number.sem_battery_assist_floor_soc","assist_floor",t,"zone_help_floor")}
                ${this._renderStepper("number.sem_battery_priority_soc","priority_soc",t,"zone_help_priority")}
            </div>
            <div class="stepper-pair">
                ${this._renderStepper("number.sem_battery_minimum_soc","minimum_soc",t,"setting_help_minimum_soc")}
                ${this._renderStepper("number.sem_battery_resume_soc","resume_soc",t,"setting_help_resume_soc")}
            </div>
        `}_renderTariff(t){const e=this._options||{},i=this._hass?.states["sensor.sem_tariff_current_import_rate"],s=i?i.state:"—",r=i?.attributes?.unit_of_measurement||"",a=this._hass?.config?.currency||"EUR",o=[{value:"static",label:this._t("config_tariff_mode_static")},{value:"dynamic",label:this._t("config_tariff_mode_dynamic")},{value:"calendar",label:this._t("config_tariff_mode_calendar")}],n=[{value:"percentile",label:this._t("config_tariff_class_percentile")},{value:"static",label:this._t("config_tariff_class_static")}],l=e.tariff_mode||"static";return W`
            <div class="readonly-row tariff-rate-row">
                <ha-icon icon="mdi:flash" style="--mdc-icon-size:18px;color:#ff9800"></ha-icon>
                <span class="ctrl-label" style="flex:1">${this._t("current_electricity_price")}</span>
                <span class="readonly-value tariff-rate-value">${s} ${r}</span>
            </div>
            ${this._renderOptionSelect("tariff_mode","config_tariff_mode",o,e,"config_help_tariff_mode","static")}
            ${"dynamic"===l?W`
                ${this._renderPicker("dynamic_tariff_entity","config_dynamic_tariff_entity","sensor",null,e,"config_help_dynamic_tariff_entity")}
                ${this._renderPicker("dynamic_forecast_entity","config_dynamic_forecast_entity","sensor",null,e,"config_help_dynamic_forecast_entity")}
                ${this._renderPicker("dynamic_feedin_entity","config_dynamic_feedin_entity","sensor",null,e,"config_help_dynamic_feedin_entity")}
                ${this._renderOptionSelect("tariff_classification_mode","config_tariff_class_mode",n,e,"config_help_tariff_class_mode","percentile")}
            `:K}
            <div class="stepper-pair">
                ${this._renderStepper("number.sem_cheap_price_threshold","cheap_threshold",t,"setting_help_cheap_threshold")}
                ${this._renderStepper("number.sem_expensive_price_threshold","expensive_threshold",t,"setting_help_expensive_threshold")}
            </div>
            ${this._renderOptionNumberInput("electricity_import_rate","config_import_rate",{min:0,max:1,step:.001,unit:`${a}/kWh`,default:.3387},e,"config_help_import_rate")}
            ${this._renderOptionNumberInput("electricity_off_peak_rate","config_off_peak_rate",{min:0,max:1,step:.001,unit:`${a}/kWh`,default:.3387},e,"config_help_off_peak_rate")}
            ${this._renderOptionNumberInput("electricity_export_rate","config_export_rate",{min:0,max:.5,step:.001,unit:`${a}/kWh`,default:.075},e,"config_help_export_rate")}
            ${this._renderOptionNumberInput("demand_charge_rate","config_demand_charge_rate",{min:0,max:20,step:.01,unit:`${a}/kW/Mt`,default:4.32},e,"config_help_demand_charge_rate")}
            ${this._renderPicker("grid_import_power_entity","config_grid_import_entity","sensor","power",e,"config_help_grid_import_entity")}
            ${this._renderPicker("grid_export_power_entity","config_grid_export_entity","sensor","power",e,"config_help_grid_export_entity")}
        `}_renderHeatPump(t){const e="on"===this._val("heat_pump_registered"),i=this._options||{},s=e?W`
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
                ${this._renderPicker("heat_pump_relay1_entity","config_hp_relay1","switch",null,i,"config_help_hp_relay")}
                ${this._renderPicker("heat_pump_relay2_entity","config_hp_relay2","switch",null,i,"config_help_hp_relay")}
                ${this._renderPicker("heat_pump_climate_entity","config_hp_climate","climate",null,i,"config_help_hp_climate")}
                ${this._renderPicker("heat_pump_power_sensor","config_hp_power_sensor","sensor","power",i,"config_help_hp_power_sensor")}
                ${e?this._renderStepper("number.sem_heat_pump_boost_offset","heat_pump_boost_offset",t,"config_help_hp_boost_offset"):this._renderOptionSlider("heat_pump_boost_offset","heat_pump_boost_offset",{min:0,max:10,step:.5,unit:"°C",default:2},i,"config_help_hp_boost_offset")}
                ${this._renderOptionSlider("heat_pump_max_setpoint","config_hp_max_setpoint",{min:30,max:80,step:1,unit:"°C",default:55},i,"config_help_hp_max_setpoint")}
                ${this._renderOptionSlider("heat_pump_priority","config_hp_priority",{min:1,max:10,step:1,unit:"",default:4},i,"config_help_hp_priority")}
            </div>
        `}_renderTargetTypeSelectNested(t,e,i){const s=e.ev_target_type||"kwh",r=!!e.vehicle_soc_entity,a=`ev_chargers.${t}.ev_target_type`,o=this._saveStatus[a];return W`
            <div class="stepper-cell">
                <div class="ctrl-row">
                    <span class="ctrl-label">${this._t("config_ev_target_type")}</span>
                    <select class="sem-select" .value=${s} @change=${async e=>{const s=e.target.value,r=(i.ev_chargers||[]).map(t=>({...t}));r[t]||(r[t]={}),r[t].ev_target_type=s,await this._saveOption("ev_chargers",r,a)}}>
                        <option value="kwh" ?selected=${"soc"!==s}>
                            ${this._t("config_ev_target_type_kwh")}
                        </option>
                        <option value="soc" ?disabled=${!r}
                                            ?selected=${"soc"===s}>
                            ${this._t("config_ev_target_type_soc")}${r?"":" — "+this._t("config_ev_target_type_requires_sensor")}
                        </option>
                    </select>
                </div>
                ${"saving"===o?W`<div class="save-status">${this._t("config_saving")}…</div>`:K}
                ${"ok"===o?W`<div class="save-status ok">✓</div>`:K}
                ${this._showHelp?W`<div class="setting-help-text">${this._t("config_help_ev_target_type")}</div>`:K}
            </div>
        `}_renderPickerNested(t,e,i,s,r,a,o){const n=a.ev_chargers||[],l=n[t]?.[e]||"",c=`ev_chargers.${t}.${e}`,d=this._saveStatus[c],p=async i=>{const s=(a.ev_chargers||[]).map(t=>({...t}));s[t]||(s[t]={}),s[t][e]=i,await this._saveOption("ev_chargers",s,c)};return W`
            <div class="picker-cell">
                <div class="picker-row">
                    <span class="picker-label">${this._t(i)}</span>
                    <ha-entity-picker
                        .hass=${this._hass}
                        .value=${l}
                        .includeDomains=${[s]}
                        .includeDeviceClasses=${r?[r]:void 0}
                        .allowCustomEntity=${!1}
                        @value-changed=${t=>p(t.detail?.value||"")}>
                    </ha-entity-picker>
                </div>
                ${"saving"===d?W`<div class="save-status">${this._t("config_saving")}…</div>`:K}
                ${"ok"===d?W`<div class="save-status ok">✓ ${this._t("config_saved")}</div>`:K}
                ${this._showHelp&&o?W`<div class="setting-help-text">${this._t(o)}</div>`:K}
            </div>
        `}_renderPicker(t,e,i,s,r,a){const o=r[t]||"",n=this._saveStatus[t];return W`
            <div class="picker-cell">
                <div class="picker-row">
                    <span class="picker-label">${this._t(e)}</span>
                    <ha-entity-picker
                        .hass=${this._hass}
                        .value=${o}
                        .includeDomains=${[i]}
                        .includeDeviceClasses=${s?[s]:void 0}
                        .allowCustomEntity=${!1}
                        @value-changed=${e=>this._saveOption(t,e.detail?.value||"",t)}>
                    </ha-entity-picker>
                </div>
                ${"saving"===n?W`<div class="save-status">${this._t("config_saving")}…</div>`:K}
                ${"ok"===n?W`<div class="save-status ok">✓ ${this._t("config_saved")}</div>`:K}
                ${n&&"saving"!==n&&"ok"!==n?W`<div class="save-status err">⚠ ${n}</div>`:K}
                ${this._showHelp&&a?W`<div class="setting-help-text">${this._t(a)}</div>`:K}
            </div>
        `}_renderOptionToggle(t,e,i,s,r=!1){const a=null!=i[t]?!!i[t]:r,o=this._saveStatus[t];return W`
            <div class="stepper-cell">
                <div class="toggle-row">
                    <span class="toggle-label">${this._t(e)}</span>
                    <div class="toggle-track ${a?"on":""}"
                         @click=${()=>this._saveOption(t,!a,t)}>
                        <div class="toggle-thumb"></div>
                    </div>
                </div>
                ${"saving"===o?W`<div class="save-status">${this._t("config_saving")}…</div>`:K}
                ${"ok"===o?W`<div class="save-status ok">✓</div>`:K}
                ${this._showHelp&&s?W`<div class="setting-help-text">${this._t(s)}</div>`:K}
            </div>
        `}_renderOptionSelect(t,e,i,s,r,a){const o=null!=s[t]?s[t]:a,n=this._saveStatus[t];return W`
            <div class="stepper-cell">
                <div class="ctrl-row">
                    <span class="ctrl-label">${this._t(e)}</span>
                    <select class="sem-select"
                            .value=${o}
                            @change=${e=>this._saveOption(t,e.target.value,t)}>
                        ${i.map(t=>W`
                            <option value="${t.value}" ?selected=${t.value===o}>${t.label}</option>
                        `)}
                    </select>
                </div>
                ${"saving"===n?W`<div class="save-status">${this._t("config_saving")}…</div>`:K}
                ${"ok"===n?W`<div class="save-status ok">✓</div>`:K}
                ${this._showHelp&&r?W`<div class="setting-help-text">${this._t(r)}</div>`:K}
            </div>
        `}_renderOptionNumberInput(t,e,i,s,r){const a=null!=s[t]?s[t]:i.default,o=this._saveStatus[t],n=e=>{const s=parseFloat(e);if(Number.isNaN(s))return;const r=Math.max(i.min,Math.min(i.max,s));this._saveOption(t,r,t)};return W`
            <div class="stepper-cell">
                <div class="ctrl-row">
                    <span class="ctrl-label">${this._t(e)}</span>
                    <div class="num-input-wrap">
                        <input class="sem-num-input" type="number"
                               .value=${String(a)}
                               min=${i.min} max=${i.max} step=${i.step}
                               @change=${t=>n(t.target.value)}
                               @blur=${t=>n(t.target.value)}
                               @keydown=${t=>{"Enter"===t.key&&t.target.blur()}}>
                        ${i.unit?W`<span class="num-unit">${i.unit}</span>`:K}
                    </div>
                </div>
                ${"saving"===o?W`<div class="save-status">${this._t("config_saving")}…</div>`:K}
                ${"ok"===o?W`<div class="save-status ok">✓</div>`:K}
                ${this._showHelp&&r?W`<div class="setting-help-text">${this._t(r)}</div>`:K}
            </div>
        `}_renderOptionSlider(t,e,i,s,r){const a=null!=s[t]?s[t]:i.default,o=this._saveStatus[t],n=i.step<1?1:0,l=parseFloat(a).toFixed(n)+(i.unit?" "+i.unit:"");return W`
            <div class="stepper-cell">
                <div class="stepper-row">
                    <span class="stepper-label">${this._t(e)}</span>
                    <div class="stepper-controls">
                        <button class="stepper-minus" @click=${()=>{const e=Math.max(i.min,parseFloat(a)-i.step);this._saveOption(t,e,t)}}>−</button>
                        <span class="stepper-value">${l}</span>
                        <button class="stepper-plus" @click=${()=>{const e=Math.min(i.max,parseFloat(a)+i.step);this._saveOption(t,e,t)}}>+</button>
                    </div>
                </div>
                ${"saving"===o?W`<div class="save-status">${this._t("config_saving")}…</div>`:K}
                ${"ok"===o?W`<div class="save-status ok">✓</div>`:K}
                ${this._showHelp&&r?W`<div class="setting-help-text">${this._t(r)}</div>`:K}
            </div>
        `}_renderBatteryScheduler(t){const e=this._options||{};return W`
            <div class="setup-intro">${this._t("config_battery_scheduler_intro")}</div>
            ${this._renderOptionToggle("battery_charge_scheduler_enabled","config_bs_enabled",e,"config_help_bs_enabled",!1)}
            ${this._renderOptionNumberInput("battery_capacity_kwh","config_bs_capacity",{min:1,max:100,step:.5,unit:"kWh",default:10},e,"config_help_bs_capacity")}
            ${this._renderOptionNumberInput("battery_max_charge_power_w","config_bs_max_charge",{min:500,max:25e3,step:100,unit:"W",default:5e3},e,"config_help_bs_max_charge")}
            ${this._renderOptionSlider("battery_roundtrip_efficiency","config_bs_efficiency",{min:.7,max:.99,step:.01,unit:"",default:.92},e,"config_help_bs_efficiency")}
            ${this._renderOptionNumberInput("battery_cycle_cost","config_bs_cycle_cost",{min:0,max:.5,step:.001,unit:"EUR/kWh",default:0},e,"config_help_bs_cycle_cost")}
            ${this._renderOptionSlider("battery_precharge_trigger_hour","config_bs_trigger_hour",{min:18,max:23,step:1,unit:"h",default:21},e,"config_help_bs_trigger_hour")}
            ${this._renderOptionSlider("battery_max_target_soc","config_bs_max_target_soc",{min:50,max:100,step:5,unit:"%",default:95},e,"config_help_bs_max_target_soc")}
            ${this._renderOptionNumberInput("battery_min_deficit_kwh","config_bs_min_deficit",{min:.5,max:10,step:.5,unit:"kWh",default:2},e,"config_help_bs_min_deficit")}
            ${this._renderOptionSlider("battery_pessimism_weight","config_bs_pessimism",{min:0,max:1,step:.1,unit:"",default:.3},e,"config_help_bs_pessimism")}
            ${this._renderOptionToggle("battery_force_charge_negative_price","config_bs_force_neg",e,"config_help_bs_force_neg",!0)}
        `}_renderLoadManagement(t){const e=this._options||{};return W`
            <div class="readonly-row">
                <span class="ctrl-label">${this._t("load_management_status")}</span>
                <span class="readonly-value">${this._val("load_management_status")||"—"}</span>
            </div>
            ${this._renderOptionToggle("load_management_enabled","config_lm_enabled",e,"config_help_lm_enabled",!0)}
            ${this._renderOptionSlider("target_peak_limit","config_lm_target_peak",{min:1,max:15,step:.5,unit:"kW",default:5},e,"config_help_lm_target_peak")}
            ${this._renderOptionSlider("warning_peak_level","config_lm_warning_peak",{min:1,max:15,step:.5,unit:"kW",default:4.5},e,"config_help_lm_warning_peak")}
            ${this._renderOptionSlider("emergency_peak_level","config_lm_emergency_peak",{min:1,max:20,step:.5,unit:"kW",default:6},e,"config_help_lm_emergency_peak")}
            ${this._renderOptionToggle("critical_device_protection","config_lm_critical_protection",e,"config_help_lm_critical_protection",!0)}
            ${this._renderStepper("number.sem_maximum_grid_import","max_grid_import",t,"tile_help_max_grid_import")}
        `}_renderForecast(t){const e=this._val("forecast_source")||"none";return W`
            <div class="readonly-row">
                <span class="ctrl-label">${this._t("forecast_source")}</span>
                <span class="readonly-value">${e}</span>
            </div>
            ${"none"===e?W`<div class="overview-help">${this._t("config_forecast_install_hint")}</div>`:K}
        `}_renderNotifications(t){const e=this._options||{},i=[{value:"",label:this._t("config_notif_none")}],s=this._hass?.services||{};for(const t of Object.keys(s.notify||{}))i.push({value:t,label:`notify.${t}`});for(const t of Object.keys(s.rest_command||{}))i.push({value:t,label:`rest_command.${t}`});return W`
            <div class="setup-intro">${this._t("config_notifications_intro")}</div>
            ${this._renderOptionToggle("enable_charger_notifications","config_notif_charger",e,"config_help_notif_charger",!0)}
            ${this._renderOptionToggle("enable_mobile_notifications","config_notif_mobile",e,"config_help_notif_mobile",!1)}
            ${this._renderOptionSelect("mobile_notification_service","config_notif_service",i,e,"config_help_notif_service","")}
        `}_renderAdvanced(t){return W`
            ${this._renderToggle("switch.sem_observer_mode","observer_mode",t,"config_help_observer_mode")}
            <div class="stepper-pair">
                ${this._renderStepper("number.sem_update_interval","update_interval",t,"config_help_update_interval")}
                ${this._renderStepper("number.sem_power_delta","power_delta",t,"config_help_power_delta")}
            </div>
            <div class="stepper-pair">
                ${this._renderStepper("number.sem_current_delta","current_delta",t,"config_help_current_delta")}
                ${this._renderStepper("number.sem_soc_delta","soc_delta",t,"config_help_soc_delta")}
            </div>
            ${this._renderStepper("number.sem_minimum_solar_power","min_solar_power",t,"config_help_min_solar_power")}
        `}_renderSectionHeader(t,e){const i=this._collapsed[t.id]?"rotate(-90deg)":"rotate(0deg)",s=t.subtitleFn(this),r="overview"===t.id?"all":t.id;return W`
            <div class="section-header" @click=${()=>this._toggleSection(t.id)}>
                <ha-icon icon="${t.icon}" style="--mdc-icon-size:20px;color:${t.color}"></ha-icon>
                <span class="section-title-text">${this._t(t.titleKey)}</span>
                <span class="section-subtitle">${s}</span>
                <sem-diagnose-button
                    .hass=${this._hass}
                    section="${r}"
                    label="${this._t("config_diagnose")}"
                    @click=${t=>t.stopPropagation()}>
                </sem-diagnose-button>
                <ha-icon class="chevron" icon="mdi:chevron-down"
                         style="--mdc-icon-size:18px;transform:${i}"></ha-icon>
            </div>
        `}_renderSection(t,e,i){const s=this._collapsed[t.id];return W`
            <div class="section ${s?"":"expanded"}"
                 style="--section-accent: ${t.color}">
                ${this._renderSectionHeader(t,i)}
                <div class="section-content ${s?"":"expanded"}">
                    <div class="section-body">
                        ${e(i)}
                    </div>
                </div>
            </div>
        `}render(){if(!this._config)return K;const t=this._theme(),e=!1!==t.isDark,i=t.accent||"#42a5f5",s={overview:t=>this._renderOverview(t),ev_chargers:t=>this._renderEvChargers(t),battery_zones:t=>this._renderBatteryZones(t),tariff:t=>this._renderTariff(t),heat_pump:t=>this._renderHeatPump(t),battery_scheduler:t=>this._renderBatteryScheduler(t),load_management:t=>this._renderLoadManagement(t),forecast:t=>this._renderForecast(t),notifications:t=>this._renderNotifications(t),advanced:t=>this._renderAdvanced(t)};return W`
            <style>
                :host { display: block; contain: layout style paint; }
                .wrap {
                    padding: 16px;
                    background:
                        radial-gradient(ellipse 70% 60% at 50% 25%, rgba(141,200,146,0.06) 0%, transparent 100%),
                        radial-gradient(circle at 2px 2px, ${t.dotColor} 0.7px, transparent 0.7px);
                    background-size: 100% 100%, 50px 50px;
                    font-family: 'Segoe UI','Roboto',sans-serif;
                    color: var(--primary-text-color, ${t.text});
                }
                .card-help-bar {
                    display: flex; justify-content: flex-end;
                    margin: -4px 0 6px;
                }
                .help-toggle {
                    cursor: pointer;
                    color: var(--secondary-text-color, ${t.textSec});
                    opacity: 0.6;
                    flex-shrink: 0;
                    transition: opacity 0.15s, color 0.15s;
                    user-select: none;
                    padding: 4px;
                    border-radius: 50%;
                }
                .help-toggle:hover { opacity: 1; }
                .help-toggle.on { color: ${i}; opacity: 1; }

                .section {
                    margin-bottom: 10px;
                    border-radius: 14px;
                    background: ${t.surface};
                    border: 1px solid ${t.surfaceBorder};
                    overflow: hidden;
                    transition: border-color 0.2s, box-shadow 0.2s;
                    position: relative;
                }
                .section.expanded {
                    border-color: color-mix(in srgb, var(--section-accent) 40%, ${t.surfaceBorder});
                    box-shadow: inset 3px 0 0 0 var(--section-accent);
                }
                .section:hover { border-color: ${e?"rgba(255,255,255,0.18)":"rgba(0,0,0,0.12)"}; }
                .section-header {
                    display: flex; align-items: center; gap: 10px;
                    padding: 13px 14px; cursor: pointer; user-select: none;
                    transition: background 0.15s;
                }
                .section.expanded .section-header {
                    background: color-mix(in srgb, var(--section-accent) 6%, transparent);
                }
                .section-title-text {
                    font-size: 15px; font-weight: 600; white-space: nowrap; letter-spacing: 0.1px;
                }
                .section-subtitle {
                    flex: 1; font-size: 13px;
                    color: var(--secondary-text-color, ${t.textSec});
                    text-align: right; white-space: nowrap;
                    overflow: hidden; text-overflow: ellipsis; margin-right: 4px;
                }
                .chevron { transition: transform 0.25s ease; color: var(--secondary-text-color, ${t.textSec}); }
                .section-content {
                    max-height: 0; opacity: 0; overflow: hidden;
                    transition: max-height 0.3s ease, opacity 0.2s ease;
                }
                .section-content.expanded { max-height: 2000px; opacity: 1; }
                .section-body { padding: 0 14px 14px; }
                .section-footer { display: flex; justify-content: flex-end; margin-top: 10px; }

                /* Overview tiles */
                .overview-grid { display: flex; flex-direction: column; gap: 6px; margin: 6px 0; }
                .overview-item { display: flex; align-items: center; gap: 8px; font-size: 13px; padding: 6px 0; }
                .overview-item span { flex: 1; }
                .overview-status { font-weight: 700; font-size: 14px; }
                .overview-status.ok { color: #8DC892; }
                .overview-status.warn { color: #ff9800; }
                .overview-help { font-size: 12px; color: var(--secondary-text-color, ${t.textSec}); padding: 4px 0; }
                .overview-actions { display: flex; gap: 8px; margin-top: 10px; }

                .empty-state {
                    display: flex; flex-direction: column; align-items: center;
                    gap: 8px; padding: 16px 8px; text-align: center;
                }
                .empty-title { font-size: 14px; font-weight: 600; color: var(--primary-text-color, ${t.text}); }
                .empty-help {
                    font-size: 12px; color: var(--secondary-text-color, ${t.textSec});
                    max-width: 320px; line-height: 1.4;
                }
                .info-box-text { font-size: 13px; color: var(--secondary-text-color, ${t.textSec}); padding: 6px 0; line-height: 1.4; }

                /* Inline edit primitives (same look as Control card) */
                .ctrl-row { display: flex; align-items: center; justify-content: space-between; padding: 8px 0; }
                .ctrl-label { font-size: 14px; font-weight: 500; }
                .sem-select {
                    background: ${t.surface};
                    border: 1px solid ${t.surfaceBorder};
                    border-radius: 8px;
                    color: var(--primary-text-color, ${t.text});
                    padding: 6px 10px; font-size: 14px; font-family: inherit;
                    cursor: pointer; min-width: 120px; outline: none;
                }
                .sem-select option { background: ${e?"#1e232d":"#fff"}; color: ${e?"#e0e0e0":"#333"}; }
                .stepper-row { display: flex; align-items: center; justify-content: space-between; padding: 7px 0; }
                .stepper-label {
                    font-size: 14px; font-weight: 500; flex: 1; min-width: 0;
                    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
                }
                .stepper-controls { display: flex; align-items: center; gap: 2px; flex-shrink: 0; }
                .stepper-minus, .stepper-plus {
                    width: 30px; height: 30px; border-radius: 8px;
                    border: 1px solid ${t.surfaceBorder};
                    background: ${t.surface}; color: var(--primary-text-color, ${t.text});
                    font-size: 16px; font-weight: 600; cursor: pointer;
                    display: flex; align-items: center; justify-content: center;
                    transition: background 0.15s, border-color 0.15s; user-select: none;
                    padding: 0; line-height: 1;
                }
                .stepper-minus:hover, .stepper-plus:hover { background: ${t.surfaceHover}; border-color: ${i}; }
                .stepper-value {
                    font-size: 14px; font-weight: 600; min-width: 60px; text-align: center;
                    font-variant-numeric: tabular-nums;
                }
                .stepper-pair { display: grid; grid-template-columns: 1fr 1fr; gap: 0 16px; }
                @media (max-width: 480px) { .stepper-pair { grid-template-columns: 1fr; } }
                .readonly-row { display: flex; align-items: center; justify-content: space-between; padding: 7px 0; }
                .readonly-value {
                    font-size: 14px; font-weight: 600; font-variant-numeric: tabular-nums;
                    color: var(--secondary-text-color, ${t.textSec});
                }
                .tariff-rate-row { gap: 8px; border-bottom: 1px solid ${t.surfaceBorder}; margin-bottom: 8px; padding-bottom: 10px; }
                .tariff-rate-value { font-size: 15px; font-weight: 700; color: ${t.text}; }
                .toggle-row { display: flex; align-items: center; justify-content: space-between; padding: 8px 0; }
                .toggle-label { font-size: 14px; font-weight: 500; }
                .toggle-track {
                    position: relative; width: 42px; height: 24px;
                    border-radius: 12px;
                    background: ${e?"rgba(255,255,255,0.15)":"rgba(0,0,0,0.18)"};
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
                .setting-help-text {
                    font-size: 11px; line-height: 1.35;
                    color: var(--secondary-text-color, ${t.textSec});
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
                    color: var(--secondary-text-color, ${t.textSec});
                }
                .save-status.ok { color: #8DC892; }
                .save-status.err { color: var(--error-color, #d33); }

                .setup-intro {
                    font-size: 12px; line-height: 1.45;
                    color: var(--secondary-text-color, ${t.textSec});
                    padding: 6px 0 12px; border-bottom: 1px solid ${t.surfaceBorder};
                    margin-bottom: 8px;
                }
                .hp-status, .hp-form { display: flex; flex-direction: column; }
                .hp-status { margin-bottom: 6px; padding-bottom: 6px; border-bottom: 1px solid ${t.surfaceBorder}; }

                /* number input for box-mode large-range fields */
                .num-input-wrap { display: flex; align-items: center; gap: 6px; }
                .sem-num-input {
                    background: ${t.surface};
                    border: 1px solid ${t.surfaceBorder};
                    border-radius: 8px;
                    color: var(--primary-text-color, ${t.text});
                    padding: 5px 8px; font-size: 14px; font-family: inherit;
                    width: 90px; text-align: right;
                    font-variant-numeric: tabular-nums;
                    outline: none;
                }
                .sem-num-input:focus { border-color: ${i}; }
                .num-unit {
                    font-size: 12px; color: var(--secondary-text-color, ${t.textSec});
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
                    background: ${t.surface}; border: 1px solid ${t.surfaceBorder};
                    color: var(--primary-text-color, ${t.text});
                    font-size: 13px; cursor: pointer;
                    transition: background 0.15s, border-color 0.15s;
                }
                .ha-settings-btn:hover { background: ${t.surfaceHover}; border-color: ${i}; }
            </style>
            <div class="wrap">
                <div class="card-help-bar">
                    <ha-icon
                        class="help-toggle ${this._showHelp?"on":""}"
                        icon="${this._showHelp?"mdi:help-circle":"mdi:help-circle-outline"}"
                        title="${this._t("zone_help_toggle")}"
                        @click=${()=>this._toggleHelp()}
                        style="--mdc-icon-size:18px"
                    ></ha-icon>
                </div>
                ${ze.map(e=>this._renderSection(e,s[e.id],t))}
            </div>
        `}getCardSize(){return 12}static getStubConfig(){return{entity_prefix:"sensor.sem_"}}},{type:"custom:sem-config-card",name:"SEM Configuration Card",description:"In-dashboard SEM configuration surface (replaces the Settings → SEM → Configure flow for most users)",preview:!1});const De="sem-config-tab-introduced-v1";yt("sem-onboarding-banner",class extends xt{static get watchedEntities(){return[]}static get properties(){return{...super.properties,_dismissed:{state:!0}}}constructor(){super(),this._dismissed=this._isDismissed()}setConfig(t){super.setConfig(t),this._configPath=t.config_tab_path||"/config"}_isDismissed(){try{return"1"===localStorage.getItem(De)}catch(t){return!1}}_dismiss(){try{localStorage.setItem(De,"1")}catch(t){}this._dismissed=!0}_openConfig(){const t=window.location.pathname.split("/").filter(Boolean);if(t.length>=2){const e="/"+t.slice(0,-1).join("/");window.history.pushState(null,"",`${e}/config`)}else window.history.pushState(null,"",this._configPath);window.dispatchEvent(new Event("location-changed",{composed:!0})),this._dismiss()}render(){if(this._dismissed)return K;if(!this._config)return K;const t=this._theme(),e="#8DC892";return W`
            <style>
                :host { display: block; }
                .banner {
                    display: flex; align-items: center; gap: 12px;
                    padding: 14px 16px; border-radius: 14px; margin-bottom: 12px;
                    background:
                        linear-gradient(135deg, ${e}22 0%, ${e}0B 100%),
                        ${t.surface};
                    border: 1px solid ${e}55;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
                    color: var(--primary-text-color, ${t.text});
                    font-family: 'Segoe UI','Roboto',sans-serif;
                }
                .icon {
                    --mdc-icon-size: 28px;
                    color: ${e};
                    flex-shrink: 0;
                }
                .text { flex: 1; min-width: 0; }
                .title {
                    font-size: 14px; font-weight: 700; letter-spacing: 0.2px;
                    margin-bottom: 2px;
                }
                .body {
                    font-size: 12px; line-height: 1.4;
                    color: var(--secondary-text-color, ${t.textSec});
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
                    background: ${e}; color: #1a1d24;
                }
                .open:hover { background: color-mix(in srgb, ${e} 88%, white); }
                .dismiss {
                    background: transparent; color: var(--secondary-text-color, ${t.textSec});
                    border-color: ${t.surfaceBorder};
                }
                .dismiss:hover { background: ${t.surfaceHover}; }
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
        `}getCardSize(){return 1}static getStubConfig(){return{}}},{type:"custom:sem-onboarding-banner",name:"SEM Onboarding Banner",description:"One-time welcome banner pointing existing users to the new Configuration tab",preview:!1});class Fe extends xt{static get properties(){return{...super.properties,section:{type:String},label:{type:String},_open:{state:!0},_busy:{state:!0},_payload:{state:!0},_error:{state:!0},_copied:{state:!0}}}constructor(){super(),this.section="all",this.label="",this._open=!1,this._busy=!1,this._payload=null,this._error=null,this._copied=!1}static get watchedEntities(){return[]}async _click(){if(this._hass){this._open=!0,this._busy=!0,this._error=null,this._payload=null;try{const t=await this._hass.callService("solar_energy_management","diagnose",{section:this.section||"all"},void 0,void 0,!0);this._payload=t?.response||t}catch(t){this._error=t?.message||String(t),console.error("[sem-diagnose-button] failed",t)}finally{this._busy=!1}}}_close(){this._open=!1,this._copied=!1,this._payload=null,this._error=null}async _copy(){if(!this._payload)return;const t=JSON.stringify(this._payload,null,2);try{await navigator.clipboard.writeText(t),this._copied=!0,setTimeout(()=>{this._copied=!1},1500)}catch(t){console.error("[sem-diagnose-button] clipboard failed",t),this._error=this._t("config_diagnose_clipboard_failed")}}render(){const t=this._theme(),e=t.accent||"#5BC8D8",i=this.label||this._t("config_diagnose");return W`
            <style>
                :host { display: inline-flex; }
                .btn {
                    display: inline-flex; align-items: center; gap: 4px;
                    padding: 5px 10px; border-radius: 8px; cursor: pointer;
                    background: ${t.surface}; color: var(--primary-text-color, ${t.text});
                    border: 1px solid ${t.surfaceBorder};
                    font-size: 12px; font-family: inherit;
                    transition: background 0.15s, border-color 0.15s;
                }
                .btn:hover { background: ${t.surfaceHover}; border-color: ${e}; }
                .modal-backdrop {
                    position: fixed; inset: 0; background: rgba(0,0,0,0.55);
                    display: flex; align-items: center; justify-content: center;
                    z-index: 9999; padding: 20px;
                }
                .modal {
                    background: ${t.surface};
                    border: 1px solid ${t.surfaceBorder};
                    border-radius: 14px; padding: 18px;
                    max-width: 800px; width: 100%;
                    max-height: 80vh; overflow: hidden;
                    display: flex; flex-direction: column;
                    box-shadow: 0 8px 30px rgba(0,0,0,0.4);
                    color: var(--primary-text-color, ${t.text});
                    font-family: 'Segoe UI','Roboto',sans-serif;
                }
                .modal-header {
                    display: flex; align-items: center; gap: 10px;
                    padding-bottom: 12px;
                    border-bottom: 1px solid ${t.surfaceBorder};
                }
                .modal-title { font-size: 16px; font-weight: 700; flex: 1; }
                .icon-btn {
                    background: transparent; border: none;
                    color: var(--secondary-text-color, ${t.textSec});
                    cursor: pointer; padding: 4px; border-radius: 50%;
                    transition: background 0.15s;
                }
                .icon-btn:hover { background: ${t.surfaceHover}; }
                .modal-body {
                    flex: 1; overflow: auto; padding: 12px 0;
                    font-family: ui-monospace, 'SF Mono', 'Roboto Mono', monospace;
                    font-size: 11px; line-height: 1.5;
                    white-space: pre-wrap; word-break: break-word;
                    color: var(--primary-text-color, ${t.text});
                }
                .modal-footer {
                    display: flex; gap: 8px; padding-top: 12px;
                    border-top: 1px solid ${t.surfaceBorder};
                    justify-content: flex-end;
                }
                .footer-btn {
                    padding: 7px 14px; border-radius: 9px;
                    font-size: 12px; font-weight: 600; font-family: inherit;
                    cursor: pointer; border: 1px solid transparent;
                }
                .footer-btn.primary {
                    background: ${e}; color: #1a1d24;
                    border-color: ${e};
                }
                .footer-btn.primary:hover {
                    background: color-mix(in srgb, ${e} 88%, white);
                }
                .footer-btn.secondary {
                    background: transparent;
                    color: var(--secondary-text-color, ${t.textSec});
                    border-color: ${t.surfaceBorder};
                }
                .footer-btn.secondary:hover { background: ${t.surfaceHover}; }
                .footer-btn.copied {
                    background: #8DC892; color: #1a1d24;
                    border-color: #8DC892;
                }
                .busy {
                    text-align: center; padding: 30px;
                    color: var(--secondary-text-color, ${t.textSec});
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
                <div class="modal-backdrop" @click=${t=>t.target.classList.contains("modal-backdrop")&&this._close()}>
                    <div class="modal">
                        <div class="modal-header">
                            <ha-icon icon="mdi:stethoscope" style="--mdc-icon-size:18px;color:${e}"></ha-icon>
                            <span class="modal-title">${this._t("config_diagnose")} — ${this.section}</span>
                            <button class="icon-btn" @click=${this._close} title="${this._t("cancel")||"Close"}">
                                <ha-icon icon="mdi:close" style="--mdc-icon-size:18px"></ha-icon>
                            </button>
                        </div>
                        <div class="modal-body">
                            ${this._busy?W`<div class="busy">${this._t("config_diagnose_busy")||"Collecting diagnostics…"}</div>`:K}
                            ${this._error?W`<div class="error">${this._error}</div>`:K}
                            ${this._busy||this._error||!this._payload?K:W`${JSON.stringify(this._payload,null,2)}`}
                        </div>
                        <div class="modal-footer">
                            <button class="footer-btn secondary" @click=${this._close}>
                                ${this._t("cancel")||"Close"}
                            </button>
                            ${this._payload?W`
                                <button class="footer-btn ${this._copied?"copied":"primary"}" @click=${this._copy}>
                                    ${this._copied?this._t("copied"):this._t("config_diagnose_copy")||"Copy to clipboard"}
                                </button>
                            `:K}
                        </div>
                    </div>
                </div>
            `:K}
        `}}customElements.get("sem-diagnose-button")||customElements.define("sem-diagnose-button",Fe),console.info("%c SEM Cards %c Lit Bundle ","color: #4db6ac; font-weight: bold; background: #1e232d; padding: 2px 6px; border-radius: 4px 0 0 4px;","color: #ff9800; background: #1e232d; padding: 2px 6px; border-radius: 0 4px 4px 0;");
