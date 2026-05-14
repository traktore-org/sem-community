const t=globalThis,e=t.ShadowRoot&&(void 0===t.ShadyCSS||t.ShadyCSS.nativeShadow)&&"adoptedStyleSheets"in Document.prototype&&"replace"in CSSStyleSheet.prototype,i=Symbol(),s=new WeakMap;let r=class{constructor(t,e,s){if(this._$cssResult$=!0,s!==i)throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");this.cssText=t,this.t=e}get styleSheet(){let t=this.o;const i=this.t;if(e&&void 0===t){const e=void 0!==i&&1===i.length;e&&(t=s.get(i)),void 0===t&&((this.o=t=new CSSStyleSheet).replaceSync(this.cssText),e&&s.set(i,t))}return t}toString(){return this.cssText}};const a=(t,...e)=>{const s=1===t.length?t[0]:e.reduce((e,i,s)=>e+(t=>{if(!0===t._$cssResult$)return t.cssText;if("number"==typeof t)return t;throw Error("Value passed to 'css' function must be a 'css' function result: "+t+". Use 'unsafeCSS' to pass non-literal values, but take care to ensure page security.")})(i)+t[s+1],t[0]);return new r(s,t,i)},o=e?t=>t:t=>t instanceof CSSStyleSheet?(t=>{let e="";for(const i of t.cssRules)e+=i.cssText;return(t=>new r("string"==typeof t?t:t+"",void 0,i))(e)})(t):t,{is:n,defineProperty:l,getOwnPropertyDescriptor:c,getOwnPropertyNames:d,getOwnPropertySymbols:h,getPrototypeOf:p}=Object,g=globalThis,_=g.trustedTypes,u=_?_.emptyScript:"",f=g.reactiveElementPolyfillSupport,m=(t,e)=>t,v={toAttribute(t,e){switch(e){case Boolean:t=t?u:null;break;case Object:case Array:t=null==t?t:JSON.stringify(t)}return t},fromAttribute(t,e){let i=t;switch(e){case Boolean:i=null!==t;break;case Number:i=null===t?null:Number(t);break;case Object:case Array:try{i=JSON.parse(t)}catch(t){i=null}}return i}},y=(t,e)=>!n(t,e),x={attribute:!0,type:String,converter:v,reflect:!1,useDefault:!1,hasChanged:y};Symbol.metadata??=Symbol("metadata"),g.litPropertyMetadata??=new WeakMap;let b=class extends HTMLElement{static addInitializer(t){this._$Ei(),(this.l??=[]).push(t)}static get observedAttributes(){return this.finalize(),this._$Eh&&[...this._$Eh.keys()]}static createProperty(t,e=x){if(e.state&&(e.attribute=!1),this._$Ei(),this.prototype.hasOwnProperty(t)&&((e=Object.create(e)).wrapped=!0),this.elementProperties.set(t,e),!e.noAccessor){const i=Symbol(),s=this.getPropertyDescriptor(t,i,e);void 0!==s&&l(this.prototype,t,s)}}static getPropertyDescriptor(t,e,i){const{get:s,set:r}=c(this.prototype,t)??{get(){return this[e]},set(t){this[e]=t}};return{get:s,set(e){const a=s?.call(this);r?.call(this,e),this.requestUpdate(t,a,i)},configurable:!0,enumerable:!0}}static getPropertyOptions(t){return this.elementProperties.get(t)??x}static _$Ei(){if(this.hasOwnProperty(m("elementProperties")))return;const t=p(this);t.finalize(),void 0!==t.l&&(this.l=[...t.l]),this.elementProperties=new Map(t.elementProperties)}static finalize(){if(this.hasOwnProperty(m("finalized")))return;if(this.finalized=!0,this._$Ei(),this.hasOwnProperty(m("properties"))){const t=this.properties,e=[...d(t),...h(t)];for(const i of e)this.createProperty(i,t[i])}const t=this[Symbol.metadata];if(null!==t){const e=litPropertyMetadata.get(t);if(void 0!==e)for(const[t,i]of e)this.elementProperties.set(t,i)}this._$Eh=new Map;for(const[t,e]of this.elementProperties){const i=this._$Eu(t,e);void 0!==i&&this._$Eh.set(i,t)}this.elementStyles=this.finalizeStyles(this.styles)}static finalizeStyles(t){const e=[];if(Array.isArray(t)){const i=new Set(t.flat(1/0).reverse());for(const t of i)e.unshift(o(t))}else void 0!==t&&e.push(o(t));return e}static _$Eu(t,e){const i=e.attribute;return!1===i?void 0:"string"==typeof i?i:"string"==typeof t?t.toLowerCase():void 0}constructor(){super(),this._$Ep=void 0,this.isUpdatePending=!1,this.hasUpdated=!1,this._$Em=null,this._$Ev()}_$Ev(){this._$ES=new Promise(t=>this.enableUpdating=t),this._$AL=new Map,this._$E_(),this.requestUpdate(),this.constructor.l?.forEach(t=>t(this))}addController(t){(this._$EO??=new Set).add(t),void 0!==this.renderRoot&&this.isConnected&&t.hostConnected?.()}removeController(t){this._$EO?.delete(t)}_$E_(){const t=new Map,e=this.constructor.elementProperties;for(const i of e.keys())this.hasOwnProperty(i)&&(t.set(i,this[i]),delete this[i]);t.size>0&&(this._$Ep=t)}createRenderRoot(){const i=this.shadowRoot??this.attachShadow(this.constructor.shadowRootOptions);return((i,s)=>{if(e)i.adoptedStyleSheets=s.map(t=>t instanceof CSSStyleSheet?t:t.styleSheet);else for(const e of s){const s=document.createElement("style"),r=t.litNonce;void 0!==r&&s.setAttribute("nonce",r),s.textContent=e.cssText,i.appendChild(s)}})(i,this.constructor.elementStyles),i}connectedCallback(){this.renderRoot??=this.createRenderRoot(),this.enableUpdating(!0),this._$EO?.forEach(t=>t.hostConnected?.())}enableUpdating(t){}disconnectedCallback(){this._$EO?.forEach(t=>t.hostDisconnected?.())}attributeChangedCallback(t,e,i){this._$AK(t,i)}_$ET(t,e){const i=this.constructor.elementProperties.get(t),s=this.constructor._$Eu(t,i);if(void 0!==s&&!0===i.reflect){const r=(void 0!==i.converter?.toAttribute?i.converter:v).toAttribute(e,i.type);this._$Em=t,null==r?this.removeAttribute(s):this.setAttribute(s,r),this._$Em=null}}_$AK(t,e){const i=this.constructor,s=i._$Eh.get(t);if(void 0!==s&&this._$Em!==s){const t=i.getPropertyOptions(s),r="function"==typeof t.converter?{fromAttribute:t.converter}:void 0!==t.converter?.fromAttribute?t.converter:v;this._$Em=s;const a=r.fromAttribute(e,t.type);this[s]=a??this._$Ej?.get(s)??a,this._$Em=null}}requestUpdate(t,e,i,s=!1,r){if(void 0!==t){const a=this.constructor;if(!1===s&&(r=this[t]),i??=a.getPropertyOptions(t),!((i.hasChanged??y)(r,e)||i.useDefault&&i.reflect&&r===this._$Ej?.get(t)&&!this.hasAttribute(a._$Eu(t,i))))return;this.C(t,e,i)}!1===this.isUpdatePending&&(this._$ES=this._$EP())}C(t,e,{useDefault:i,reflect:s,wrapped:r},a){i&&!(this._$Ej??=new Map).has(t)&&(this._$Ej.set(t,a??e??this[t]),!0!==r||void 0!==a)||(this._$AL.has(t)||(this.hasUpdated||i||(e=void 0),this._$AL.set(t,e)),!0===s&&this._$Em!==t&&(this._$Eq??=new Set).add(t))}async _$EP(){this.isUpdatePending=!0;try{await this._$ES}catch(t){Promise.reject(t)}const t=this.scheduleUpdate();return null!=t&&await t,!this.isUpdatePending}scheduleUpdate(){return this.performUpdate()}performUpdate(){if(!this.isUpdatePending)return;if(!this.hasUpdated){if(this.renderRoot??=this.createRenderRoot(),this._$Ep){for(const[t,e]of this._$Ep)this[t]=e;this._$Ep=void 0}const t=this.constructor.elementProperties;if(t.size>0)for(const[e,i]of t){const{wrapped:t}=i,s=this[e];!0!==t||this._$AL.has(e)||void 0===s||this.C(e,void 0,i,s)}}let t=!1;const e=this._$AL;try{t=this.shouldUpdate(e),t?(this.willUpdate(e),this._$EO?.forEach(t=>t.hostUpdate?.()),this.update(e)):this._$EM()}catch(e){throw t=!1,this._$EM(),e}t&&this._$AE(e)}willUpdate(t){}_$AE(t){this._$EO?.forEach(t=>t.hostUpdated?.()),this.hasUpdated||(this.hasUpdated=!0,this.firstUpdated(t)),this.updated(t)}_$EM(){this._$AL=new Map,this.isUpdatePending=!1}get updateComplete(){return this.getUpdateComplete()}getUpdateComplete(){return this._$ES}shouldUpdate(t){return!0}update(t){this._$Eq&&=this._$Eq.forEach(t=>this._$ET(t,this[t])),this._$EM()}updated(t){}firstUpdated(t){}};b.elementStyles=[],b.shadowRootOptions={mode:"open"},b[m("elementProperties")]=new Map,b[m("finalized")]=new Map,f?.({ReactiveElement:b}),(g.reactiveElementVersions??=[]).push("2.1.2");const $=globalThis,w=t=>t,k=$.trustedTypes,S=k?k.createPolicy("lit-html",{createHTML:t=>t}):void 0,C="$lit$",E=`lit$${Math.random().toFixed(9).slice(2)}$`,z="?"+E,M=`<${z}>`,D=document,F=()=>D.createComment(""),T=t=>null===t||"object"!=typeof t&&"function"!=typeof t,A=Array.isArray,I="[ \t\n\f\r]",R=/<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g,N=/-->/g,O=/>/g,P=RegExp(`>|${I}(?:([^\\s"'>=/]+)(${I}*=${I}*(?:[^ \t\n\f\r"'\`<>=]|("|')|))|$)`,"g"),B=/'/g,L=/"/g,U=/^(?:script|style|textarea|title)$/i,W=t=>(e,...i)=>({_$litType$:t,strings:e,values:i}),H=W(1),j=W(2),G=Symbol.for("lit-noChange"),K=Symbol.for("lit-nothing"),q=new WeakMap,V=D.createTreeWalker(D,129);function Y(t,e){if(!A(t)||!t.hasOwnProperty("raw"))throw Error("invalid template strings array");return void 0!==S?S.createHTML(e):e}const X=(t,e)=>{const i=t.length-1,s=[];let r,a=2===e?"<svg>":3===e?"<math>":"",o=R;for(let e=0;e<i;e++){const i=t[e];let n,l,c=-1,d=0;for(;d<i.length&&(o.lastIndex=d,l=o.exec(i),null!==l);)d=o.lastIndex,o===R?"!--"===l[1]?o=N:void 0!==l[1]?o=O:void 0!==l[2]?(U.test(l[2])&&(r=RegExp("</"+l[2],"g")),o=P):void 0!==l[3]&&(o=P):o===P?">"===l[0]?(o=r??R,c=-1):void 0===l[1]?c=-2:(c=o.lastIndex-l[2].length,n=l[1],o=void 0===l[3]?P:'"'===l[3]?L:B):o===L||o===B?o=P:o===N||o===O?o=R:(o=P,r=void 0);const h=o===P&&t[e+1].startsWith("/>")?" ":"";a+=o===R?i+M:c>=0?(s.push(n),i.slice(0,c)+C+i.slice(c)+E+h):i+E+(-2===c?e:h)}return[Y(t,a+(t[i]||"<?>")+(2===e?"</svg>":3===e?"</math>":"")),s]};class Z{constructor({strings:t,_$litType$:e},i){let s;this.parts=[];let r=0,a=0;const o=t.length-1,n=this.parts,[l,c]=X(t,e);if(this.el=Z.createElement(l,i),V.currentNode=this.el.content,2===e||3===e){const t=this.el.content.firstChild;t.replaceWith(...t.childNodes)}for(;null!==(s=V.nextNode())&&n.length<o;){if(1===s.nodeType){if(s.hasAttributes())for(const t of s.getAttributeNames())if(t.endsWith(C)){const e=c[a++],i=s.getAttribute(t).split(E),o=/([.?@])?(.*)/.exec(e);n.push({type:1,index:r,name:o[2],strings:i,ctor:"."===o[1]?it:"?"===o[1]?st:"@"===o[1]?rt:et}),s.removeAttribute(t)}else t.startsWith(E)&&(n.push({type:6,index:r}),s.removeAttribute(t));if(U.test(s.tagName)){const t=s.textContent.split(E),e=t.length-1;if(e>0){s.textContent=k?k.emptyScript:"";for(let i=0;i<e;i++)s.append(t[i],F()),V.nextNode(),n.push({type:2,index:++r});s.append(t[e],F())}}}else if(8===s.nodeType)if(s.data===z)n.push({type:2,index:r});else{let t=-1;for(;-1!==(t=s.data.indexOf(E,t+1));)n.push({type:7,index:r}),t+=E.length-1}r++}}static createElement(t,e){const i=D.createElement("template");return i.innerHTML=t,i}}function J(t,e,i=t,s){if(e===G)return e;let r=void 0!==s?i._$Co?.[s]:i._$Cl;const a=T(e)?void 0:e._$litDirective$;return r?.constructor!==a&&(r?._$AO?.(!1),void 0===a?r=void 0:(r=new a(t),r._$AT(t,i,s)),void 0!==s?(i._$Co??=[])[s]=r:i._$Cl=r),void 0!==r&&(e=J(t,r._$AS(t,e.values),r,s)),e}class Q{constructor(t,e){this._$AV=[],this._$AN=void 0,this._$AD=t,this._$AM=e}get parentNode(){return this._$AM.parentNode}get _$AU(){return this._$AM._$AU}u(t){const{el:{content:e},parts:i}=this._$AD,s=(t?.creationScope??D).importNode(e,!0);V.currentNode=s;let r=V.nextNode(),a=0,o=0,n=i[0];for(;void 0!==n;){if(a===n.index){let e;2===n.type?e=new tt(r,r.nextSibling,this,t):1===n.type?e=new n.ctor(r,n.name,n.strings,this,t):6===n.type&&(e=new at(r,this,t)),this._$AV.push(e),n=i[++o]}a!==n?.index&&(r=V.nextNode(),a++)}return V.currentNode=D,s}p(t){let e=0;for(const i of this._$AV)void 0!==i&&(void 0!==i.strings?(i._$AI(t,i,e),e+=i.strings.length-2):i._$AI(t[e])),e++}}class tt{get _$AU(){return this._$AM?._$AU??this._$Cv}constructor(t,e,i,s){this.type=2,this._$AH=K,this._$AN=void 0,this._$AA=t,this._$AB=e,this._$AM=i,this.options=s,this._$Cv=s?.isConnected??!0}get parentNode(){let t=this._$AA.parentNode;const e=this._$AM;return void 0!==e&&11===t?.nodeType&&(t=e.parentNode),t}get startNode(){return this._$AA}get endNode(){return this._$AB}_$AI(t,e=this){t=J(this,t,e),T(t)?t===K||null==t||""===t?(this._$AH!==K&&this._$AR(),this._$AH=K):t!==this._$AH&&t!==G&&this._(t):void 0!==t._$litType$?this.$(t):void 0!==t.nodeType?this.T(t):(t=>A(t)||"function"==typeof t?.[Symbol.iterator])(t)?this.k(t):this._(t)}O(t){return this._$AA.parentNode.insertBefore(t,this._$AB)}T(t){this._$AH!==t&&(this._$AR(),this._$AH=this.O(t))}_(t){this._$AH!==K&&T(this._$AH)?this._$AA.nextSibling.data=t:this.T(D.createTextNode(t)),this._$AH=t}$(t){const{values:e,_$litType$:i}=t,s="number"==typeof i?this._$AC(t):(void 0===i.el&&(i.el=Z.createElement(Y(i.h,i.h[0]),this.options)),i);if(this._$AH?._$AD===s)this._$AH.p(e);else{const t=new Q(s,this),i=t.u(this.options);t.p(e),this.T(i),this._$AH=t}}_$AC(t){let e=q.get(t.strings);return void 0===e&&q.set(t.strings,e=new Z(t)),e}k(t){A(this._$AH)||(this._$AH=[],this._$AR());const e=this._$AH;let i,s=0;for(const r of t)s===e.length?e.push(i=new tt(this.O(F()),this.O(F()),this,this.options)):i=e[s],i._$AI(r),s++;s<e.length&&(this._$AR(i&&i._$AB.nextSibling,s),e.length=s)}_$AR(t=this._$AA.nextSibling,e){for(this._$AP?.(!1,!0,e);t!==this._$AB;){const e=w(t).nextSibling;w(t).remove(),t=e}}setConnected(t){void 0===this._$AM&&(this._$Cv=t,this._$AP?.(t))}}class et{get tagName(){return this.element.tagName}get _$AU(){return this._$AM._$AU}constructor(t,e,i,s,r){this.type=1,this._$AH=K,this._$AN=void 0,this.element=t,this.name=e,this._$AM=s,this.options=r,i.length>2||""!==i[0]||""!==i[1]?(this._$AH=Array(i.length-1).fill(new String),this.strings=i):this._$AH=K}_$AI(t,e=this,i,s){const r=this.strings;let a=!1;if(void 0===r)t=J(this,t,e,0),a=!T(t)||t!==this._$AH&&t!==G,a&&(this._$AH=t);else{const s=t;let o,n;for(t=r[0],o=0;o<r.length-1;o++)n=J(this,s[i+o],e,o),n===G&&(n=this._$AH[o]),a||=!T(n)||n!==this._$AH[o],n===K?t=K:t!==K&&(t+=(n??"")+r[o+1]),this._$AH[o]=n}a&&!s&&this.j(t)}j(t){t===K?this.element.removeAttribute(this.name):this.element.setAttribute(this.name,t??"")}}class it extends et{constructor(){super(...arguments),this.type=3}j(t){this.element[this.name]=t===K?void 0:t}}class st extends et{constructor(){super(...arguments),this.type=4}j(t){this.element.toggleAttribute(this.name,!!t&&t!==K)}}class rt extends et{constructor(t,e,i,s,r){super(t,e,i,s,r),this.type=5}_$AI(t,e=this){if((t=J(this,t,e,0)??K)===G)return;const i=this._$AH,s=t===K&&i!==K||t.capture!==i.capture||t.once!==i.once||t.passive!==i.passive,r=t!==K&&(i===K||s);s&&this.element.removeEventListener(this.name,this,i),r&&this.element.addEventListener(this.name,this,t),this._$AH=t}handleEvent(t){"function"==typeof this._$AH?this._$AH.call(this.options?.host??this.element,t):this._$AH.handleEvent(t)}}class at{constructor(t,e,i){this.element=t,this.type=6,this._$AN=void 0,this._$AM=e,this.options=i}get _$AU(){return this._$AM._$AU}_$AI(t){J(this,t)}}const ot=$.litHtmlPolyfillSupport;ot?.(Z,tt),($.litHtmlVersions??=[]).push("3.3.3");const nt=globalThis;let lt=class extends b{constructor(){super(...arguments),this.renderOptions={host:this},this._$Do=void 0}createRenderRoot(){const t=super.createRenderRoot();return this.renderOptions.renderBefore??=t.firstChild,t}update(t){const e=this.render();this.hasUpdated||(this.renderOptions.isConnected=this.isConnected),super.update(t),this._$Do=((t,e,i)=>{const s=i?.renderBefore??e;let r=s._$litPart$;if(void 0===r){const t=i?.renderBefore??null;s._$litPart$=r=new tt(e.insertBefore(F(),t),t,void 0,i??{})}return r._$AI(t),r})(e,this.renderRoot,this.renderOptions)}connectedCallback(){super.connectedCallback(),this._$Do?.setConnected(!0)}disconnectedCallback(){super.disconnectedCallback(),this._$Do?.setConnected(!1)}render(){return G}};lt._$litElement$=!0,lt.finalized=!0,nt.litElementHydrateSupport?.({LitElement:lt});const ct=nt.litElementPolyfillSupport;ct?.({LitElement:lt}),(nt.litElementVersions??=[]).push("4.2.2");const dt={solar:"#ff9800",gridImport:"#488fc2",gridExport:"#8353d1",batteryOut:"#4db6ac",battery:"#4db6ac",home:"#5BC8D8",ev:"#8DC892",inverter:"#96CAEE"},ht=["#FF8A65","#AED581","#CE93D8","#64B5F6","#ff9800","#96CAEE"];function pt(t){if(null==t||isNaN(t))return"— W";return Math.abs(t)>=1e3?`${(t/1e3).toFixed(1)} kW`:`${Math.round(t)} W`}function gt(t){const e=Math.abs(t);if(e<=0)return 4;const i=4-.9*Math.log10(Math.max(e,1));return Math.max(.5,Math.min(4,i))}function _t(t){if(!t)return"EUR";const e=t.states?.["sensor.sem_daily_costs"];return e?.attributes?.unit_of_measurement?e.attributes.unit_of_measurement:t.config?.currency||"EUR"}function ut(t,e,i){return`radial-gradient(ellipse 70% 60% at 50% 25%, ${e}${Math.round(.06*255).toString(16).padStart(2,"0")} 0%, transparent 100%),\n            radial-gradient(circle at 2px 2px, ${t.dotColor} 0.7px, transparent 0.7px)`}function ft(t,e,i){customElements.get(t)||(customElements.define(t,e),i&&(window.customCards=window.customCards||[],window.customCards.push(i)))}class mt extends lt{constructor(){super(),this._hass=null,this._config=null,this._lang=null,this._localizeReady=!1,this._prevVals={},this._frozenEntities={},this._holdTimers={},this._holdIntervals={},this._cachedTheme=null,this._updateTimer=null}set hass(t){this._hass,this._hass=t;const e=t?.language,i="function"==typeof semLocalize;let s=!1;if((e!==this._lang||i&&!this._localizeReady)&&(this._lang=e,this._localizeReady=i,s=!0),this._isFrozen()&&!s)return;const r=this.constructor.watchedEntities||[];if(r.length>0&&!s){const e=t.states[r[0]]?.state;if("unavailable"===e||"unknown"===e)return}let a=!1;for(const e of r){const i=t.states[e]?.state;if(this._prevVals[e]!==i){a=!0;break}}if(a||s){for(const e of r)this._prevVals[e]=t.states[e]?.state;this._scheduleUpdate()}}get hass(){return this._hass}_scheduleUpdate(){this._updateTimer||(this._updateTimer=setTimeout(()=>{this._updateTimer=null,this.requestUpdate()},16))}_theme(){return this._cachedTheme||(this._cachedTheme=function(){const t=document.documentElement,e=getComputedStyle(t),i=(t,i)=>e.getPropertyValue(t).trim()||i,s=i("--primary-text-color","#e0e0e0"),r=i("--secondary-text-color","#888888"),a=i("--card-background-color","rgba(30,35,45,0.5)"),o=i("--divider-color","rgba(255,255,255,0.12)"),n=i("--secondary-background-color","rgba(255,255,255,0.06)"),l=i("--ha-card-box-shadow","0 2px 8px rgba(0,0,0,0.15)"),c=i("--primary-color","#42a5f5"),d=(()=>{const t=i("--primary-background-color","#111"),e=t.match(/\d+/g);return e&&e.length>=3?(.299*+e[0]+.587*+e[1]+.114*+e[2])/255<.5:!(t.startsWith("#f")||t.startsWith("#e")||t.startsWith("#d")||t.startsWith("#c")||t.startsWith("rgb(2"))})();return{text:s,textSec:r,cardBg:a,divider:o,bgSec:n,shadow:l,accent:c,isDark:d,textTertiary:d?"rgba(255,255,255,0.45)":"rgba(0,0,0,0.50)",textDisabled:d?"rgba(255,255,255,0.26)":"rgba(0,0,0,0.30)",surface:d?"rgba(255,255,255,0.06)":"rgba(0,0,0,0.03)",surfaceHover:d?"rgba(255,255,255,0.10)":"rgba(0,0,0,0.06)",surfaceBorder:d?"rgba(255,255,255,0.12)":"rgba(0,0,0,0.08)",dotColor:d?"rgba(128,128,128,0.05)":"rgba(128,128,128,0.06)",glowAlpha:d?.05:.03,tooltipBg:d?"rgba(20,20,30,0.95)":"rgba(255,255,255,0.95)",tooltipText:d?"#e0e0e0":"#333333",tooltipBorder:d?"rgba(255,255,255,0.15)":"rgba(0,0,0,0.12)"}}()),this._cachedTheme}_t(t){return t?"function"==typeof semLocalize?semLocalize(t,this._hass?.language):t:""}_state(t,e=0){const i=this._frozenEntities[t];if(i)return i.value;const s=this._hass?.states[t];return s&&"unavailable"!==s.state&&"unknown"!==s.state&&parseFloat(s.state)||e}_stateStr(t){const e=this._frozenEntities[t];if(e)return String(e.value);const i=this._hass?.states[t];return i&&"unavailable"!==i.state&&"unknown"!==i.state?i.state:""}_stateAttrs(t){return this._hass?.states[t]?.attributes||{}}_freezeEntity(t,e){const i=this._frozenEntities[t];i?.timer&&clearTimeout(i.timer),this._frozenEntities[t]={value:e,timer:setTimeout(()=>{delete this._frozenEntities[t],this.requestUpdate()},1500)}}_isFrozen(){return Object.keys(this._frozenEntities).length>0}async _callService(t,e,i){if(this._hass)try{await this._hass.callService(t,e,i)}catch(t){console.error(`[SEM ${this.tagName}]`,t)}}_setNumber(t,e){const i=this._hass?.states[t];if(!i)return;const s=parseFloat(i.attributes.min)||0,r=parseFloat(i.attributes.max)||100,a=Math.max(s,Math.min(r,e));this._freezeEntity(t,a),this.requestUpdate(),this._callService("number","set_value",{entity_id:t,value:a})}_stepNumber(t,e){const i=this._hass?.states[t];if(!i)return;const s=this._frozenEntities[t],r=s?s.value:parseFloat(i.state)||0,a=parseFloat(i.attributes.step)||1;this._setNumber(t,r+e*a)}_toggleSwitch(t){const e=this._hass?.states[t];if(!e)return;const i="on"===e.state?"off":"on";this._freezeEntity(t,i),this.requestUpdate();const s="on"===e.state?"turn_off":"turn_on";this._callService("switch",s,{entity_id:t})}_selectOption(t,e){this._freezeEntity(t,e),this.requestUpdate(),this._callService("select","select_option",{entity_id:t,option:e})}_startHold(t,e){this._stopHold(t),this._holdTimers[t]=setTimeout(()=>{this._holdIntervals[t]=setInterval(()=>{this._stepNumber(t,e)},150)},400)}_stopHold(t){clearTimeout(this._holdTimers[t]),clearInterval(this._holdIntervals[t]),delete this._holdTimers[t],delete this._holdIntervals[t]}updated(){if(window._semDebug){this.style.outline="2px solid red",this.style.outlineOffset="-2px",clearTimeout(this._debugFlashTimer),this._debugFlashTimer=setTimeout(()=>{this.style.outline="",this.style.outlineOffset=""},200);const t=this.tagName.toLowerCase();window._semRenderLog||(window._semRenderLog={}),window._semRenderLog[t]=(window._semRenderLog[t]||0)+1}}connectedCallback(){if(super.connectedCallback(),window._semDebug&&console.log(`[SEM DEBUG] ${this.tagName} connectedCallback`),!this._localizeReady){let t=0;this._localizeCheckTimer=setInterval(()=>{t++,"function"==typeof semLocalize&&this._hass?(clearInterval(this._localizeCheckTimer),this._localizeCheckTimer=null,this._localizeReady=!0,this.requestUpdate()):"function"==typeof semLocalize?(this._localizeReady=!0,clearInterval(this._localizeCheckTimer),this._localizeCheckTimer=null):t>=50&&(clearInterval(this._localizeCheckTimer),this._localizeCheckTimer=null)},200)}}disconnectedCallback(){super.disconnectedCallback(),window._semDebug&&console.log(`[SEM DEBUG] ${this.tagName} disconnectedCallback !!!`),this._localizeCheckTimer&&(clearInterval(this._localizeCheckTimer),this._localizeCheckTimer=null),this._updateTimer&&(clearTimeout(this._updateTimer),this._updateTimer=null);for(const t of Object.keys(this._holdTimers))this._stopHold(t);for(const t of Object.keys(this._frozenEntities))clearTimeout(this._frozenEntities[t]?.timer);this._frozenEntities={}}setConfig(t){this._config=t}getCardSize(){return 4}static getStubConfig(){return{}}}ft("sem-title-card",class extends mt{static get watchedEntities(){return[]}constructor(){super(),this._renderedSubtitle=null,this._templateUnsub=null,this._templateSubbed=!1}setConfig(t){super.setConfig(t),this._unsubTemplate(),this._templateSubbed=!1,this._renderedSubtitle=null}_hasJinja(t){return t&&(t.includes("{%")||t.includes("{{"))}set hass(t){this._hass,this._hass=t;const e=t?.language,i="function"==typeof semLocalize;(e!==this._lang||i&&!this._localizeReady)&&(this._lang=e,this._localizeReady=i,this.requestUpdate()),this._hasJinja(this._config?.subtitle)&&!this._templateSubbed&&this._subscribeTemplate()}_subscribeTemplate(){if(!this._hass?.connection||this._templateSubbed)return;this._templateSubbed=!0;const t=this._config.subtitle;this._hass.connection.subscribeMessage(t=>{const e=t.result;e!==this._renderedSubtitle&&(this._renderedSubtitle=e,this.requestUpdate())},{type:"render_template",template:t,variables:{}}).then(t=>{this._templateUnsub=t}).catch(()=>{this._renderedSubtitle=this._config.subtitle,this.requestUpdate()})}_unsubTemplate(){this._templateUnsub&&(this._templateUnsub(),this._templateUnsub=null)}disconnectedCallback(){super.disconnectedCallback(),this._unsubTemplate()}render(){if(!this._config)return K;const t=this._t(this._config.title_key||this._config.title||"");let e="";e=this._hasJinja(this._config.subtitle)?this._renderedSubtitle||"":this._t(this._config.subtitle||"");const i=this._theme();return H`
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
                ${e?H`<div class="subtitle">${e}</div>`:K}
                <div class="divider"></div>
            </div>
        `}getCardSize(){return 1}static getStubConfig(){return{title:"Section Title"}}},{type:"sem-title-card",name:"SEM Title Card",description:"Runtime-translated section header for SEM dashboard"});const vt=(t,e)=>"function"==typeof semLocalize?semLocalize(t,e?.language):t,yt={home:{titleKey:"home",subtitleKey:"home_sub",color:"#5BC8D8",icon:()=>j`
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
            <circle cx="12" cy="-8" r="4" fill="currentColor" opacity="0.6" stroke="none"/>`},costs:{titleKey:"costs",subtitleKey:"costs_sub",color:"#f06292",icon:()=>j`
            <circle cx="0" cy="0" r="16" stroke-width="2"/>
            <text x="0" y="6" text-anchor="middle" font-size="18" font-weight="700"
                  fill="currentColor" opacity="0.7" stroke="none"
                  font-family="'Segoe UI','Roboto',sans-serif">$</text>`},system:{titleKey:"system",subtitleKey:"system_sub",color:"#96CAEE",icon:()=>j`
            <path d="M-16,4 L-8,-8 L0,0 L6,-12 L10,-4 L16,4" stroke-width="2" fill="none"/>
            <line x1="-16" y1="8" x2="16" y2="8" stroke-width="1" opacity="0.3"/>`}};ft("sem-tab-header",class extends mt{static get watchedEntities(){return[]}constructor(){super(),this._tab="home",this._prefix="sensor.sem_",this._responsiveApplied=!1,this._lastStatsKey=""}connectedCallback(){super.connectedCallback(),this._applyResponsiveContainer()}_applyResponsiveContainer(){this._responsiveApplied||requestAnimationFrame(()=>{let t=this;for(;t;){const e=t.getRootNode()?.host;if(!e)break;if("HUI-VERTICAL-STACK-CARD"===e.tagName){const t=e.parentElement;if(t&&"HUI-CARD"===t.tagName)return t.style.maxWidth="900px",t.style.margin="0 auto",t.style.display="block",void(this._responsiveApplied=!0)}t=e}})}setConfig(t){super.setConfig(t),this._tab=t.tab||"home",this._prefix=t.entity_prefix||"sensor.sem_"}set hass(t){this._hass,this._hass=t;const e=t?.language,i="function"==typeof semLocalize;let s=!1;if((e!==this._lang||i&&!this._localizeReady)&&(this._lang=e,this._localizeReady=i,s=!0),this._isFrozen()&&!s)return;const r=this._buildStatsKey(t);(r!==this._lastStatsKey||s)&&(this._lastStatsKey=r,this.requestUpdate()),this._responsiveApplied||this._applyResponsiveContainer()}_buildStatsKey(t){if(!t)return"";const e=e=>t.states[`${this._prefix}${e}`]?.state||"",i=this._tab;return"home"===i?[e("solar_power"),e("autarky_rate"),e("daily_solar_energy")].join(","):"energy"===i?[e("daily_solar_energy"),e("daily_home_energy"),e("self_consumption_rate")].join(","):"battery"===i?[e("battery_soc"),e("battery_power"),e("battery_health")].join(","):"ev"===i?[e("ev_power"),e("daily_ev_energy"),e("charging_state")].join(","):"control"===i?[e("target_peak_limit"),e("controllable_devices_count"),e("surplus_active_devices")].join(","):"costs"===i?[e("daily_costs"),e("daily_savings"),e("daily_net_cost")].join(","):"system"===i?[e("energy_optimization_score"),e("lifetime_total_savings"),e("lifetime_co2_avoided")].join(","):""}_getState(t,e=0){const i=this._hass?.states[`${this._prefix}${t}`];return i&&"unavailable"!==i.state&&"unknown"!==i.state&&parseFloat(i.state)||e}_getStatLabels(){const t=t=>vt(t,this._hass),e=this._tab;return"home"===e?[t("solar"),t("autarky"),t("today")]:"energy"===e?[t("solar"),t("home"),t("self_use")]:"battery"===e?[t("soc"),t("power"),t("health")]:"ev"===e?[t("power"),t("today"),t("session")]:"control"===e?[t("peak"),t("devices"),t("active")]:"costs"===e?[t("cost"),t("saved"),t("net")]:"system"===e?[t("score"),t("saved"),t("co2")]:["—","—","—"]}_getStatValues(){const t=this._tab,e=_t(this._hass)||"EUR";return"home"===t?[pt(this._getState("solar_power",0)),this._getState("autarky_rate",0).toFixed(0)+"%",this._getState("daily_solar_energy",0).toFixed(1)+" kWh"]:"energy"===t?[this._getState("daily_solar_energy",0).toFixed(1)+" kWh",this._getState("daily_home_energy",0).toFixed(1)+" kWh",this._getState("self_consumption_rate",0).toFixed(0)+"%"]:"battery"===t?[this._getState("battery_soc",0).toFixed(0)+"%",pt(this._getState("battery_power",0)),this._getState("battery_health_score",100).toFixed(0)+"%"]:"ev"===t?[pt(this._getState("ev_power",0)),this._getState("daily_ev_energy",0).toFixed(1)+" kWh",this._getState("session_energy",0).toFixed(1)+" kWh"]:"control"===t?[this._getState("target_peak_limit",5).toFixed(1)+" kW",this._getState("controllable_devices_count",0).toFixed(0),this._getState("surplus_active_devices",0).toFixed(0)]:"costs"===t?[this._getState("daily_costs",0).toFixed(2)+" "+e,this._getState("daily_savings",0).toFixed(2)+" "+e,this._getState("daily_net_cost",0).toFixed(2)+" "+e]:"system"===t?[this._getState("energy_optimization_score",0).toFixed(0),this._getState("lifetime_savings",0).toFixed(0)+" "+e,this._getState("lifetime_co2_avoided",0).toFixed(0)+" kg"]:["—","—","—"]}render(){if(!this._hass||!this._config)return K;const t=yt[this._tab]||yt.home,e=this._config.title||vt(t.titleKey,this._hass),i=this._config.subtitle||vt(t.subtitleKey,this._hass),s=t.color,r=this._getStatLabels(),a=this._getStatValues(),o=this._theme(),n=o.isDark?s:`color-mix(in srgb, ${s} 65%, black)`,l=o.isDark?`0 0 12px ${s}40`:"none",c=o.isDark?.3:.18;return H`
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
                        ${r.map((t,e)=>H`
                            <div class="stat">
                                <div class="stat-value">${a[e]}</div>
                                <div class="stat-label">${t}</div>
                            </div>
                        `)}
                    </div>
                </div>
            </ha-card>
        `}getCardSize(){return 1}static getStubConfig(){return{tab:"home"}}},{type:"sem-tab-header",name:"SEM Tab Header",description:"Lumina-styled tab header with glow icon and live stats"});const xt={"clear-night":{icon:"🌙",key:"weather_clear"},cloudy:{icon:"☁️",key:"weather_cloudy"},fog:{icon:"🌫️",key:"weather_fog"},hail:{icon:"🧊",key:"weather_hail"},lightning:{icon:"⚡",key:"weather_thunder"},"lightning-rainy":{icon:"⛈️",key:"weather_thunderstorm"},partlycloudy:{icon:"⛅",key:"weather_partly_cloudy"},pouring:{icon:"🌧️",key:"weather_pouring"},rainy:{icon:"🌦️",key:"weather_rain"},snowy:{icon:"❄️",key:"weather_snow"},"snowy-rainy":{icon:"🌨️",key:"weather_sleet"},sunny:{icon:"☀️",key:"weather_sunny"},windy:{icon:"💨",key:"weather_windy"},"windy-variant":{icon:"💨",key:"weather_windy"},exceptional:{icon:"⚠️",key:"weather_exceptional"}};ft("sem-weather-card",class extends mt{constructor(){super(),this._clockTime="--:--",this._clockDate="",this._clockInterval=null}static get watchedEntities(){return[]}setConfig(t){if(!t.entity)throw new Error("sem-weather-card requires entity");super.setConfig(t)}set hass(t){this._hass,this._hass=t;const e=t?.language,i="function"==typeof semLocalize;let s=!1;if((e!==this._lang||i&&!this._localizeReady)&&(this._lang=e,this._localizeReady=i,s=!0),this._isFrozen()&&!s)return;const r=this._config?.entity;if(!r)return;const a=t?.states[r],o=(a?.state||"")+JSON.stringify(a?.attributes?.forecast?.[0]||"")+"|"+(e||"");(o!==this._lastWeatherKey||s)&&(this._lastWeatherKey=o,this.requestUpdate())}get hass(){return this._hass}connectedCallback(){super.connectedCallback(),this._updateClock(),this._clockInterval=setInterval(()=>{this._updateClock()},3e4)}disconnectedCallback(){super.disconnectedCallback(),this._clockInterval&&(clearInterval(this._clockInterval),this._clockInterval=null)}_updateClock(){const t=new Date,e=this._hass?.language||navigator.language||"en";this._clockTime=t.toLocaleTimeString(e,{hour:"2-digit",minute:"2-digit"}),this._clockDate=t.toLocaleDateString(e,{weekday:"long",day:"numeric",month:"long",year:"numeric"}),this.requestUpdate()}_renderForecastRows(t,e){const i=this._hass?.language||navigator.language||"en";return t.slice(0,e).map(t=>{const e=new Date(t.datetime).toLocaleDateString(i,{weekday:"short"}),s=xt[t.condition]?.icon||"❓",r=null!=t.templow?Math.round(t.templow):"—",a=null!=t.temperature?Math.round(t.temperature):"—",o="number"==typeof a&&"number"==typeof r?a-r:0,n=Math.max(o/30*100,10),l="number"==typeof a&&"number"==typeof r?(r+a)/2:15,c=Math.min(Math.max((l-0)/30,0),1),d=c>.5?`rgba(255,${Math.round(200-100*c)},0,0.6)`:`rgba(${Math.round(100+200*c)},${Math.round(180+40*c)},255,0.5)`;return H`
                <div class="forecast-row">
                    <span class="f-day">${e}</span>
                    <span class="f-icon">${s}</span>
                    <span class="f-low">${r}°</span>
                    <div class="f-bar-wrap">
                        <div class="f-bar" style="width:${n}%;background:${d}"></div>
                    </div>
                    <span class="f-high">${a}°</span>
                </div>
            `})}render(){if(!this._config)return K;const t=this._config.entity,e=this._config.forecast_rows||5,i=this._hass?.states[t];if(!i)return H`
                <ha-card>
                    <div style="padding:16px;color:#ef5350">Entity ${t} not found</div>
                </ha-card>
            `;const s=this._theme(),r=i.state,a=i.attributes,o=null!=a.temperature?Math.round(a.temperature):"—",n=a.temperature_unit||"°C",l=null!=a.humidity?Math.round(a.humidity):"—",c=null!=a.wind_speed?Math.round(a.wind_speed):"—",d=a.wind_speed_unit||"km/h",h=xt[r]||{icon:"❓",key:""},p=a.forecast||[];return H`
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
                            <div class="weather-icon">${h.icon}</div>
                            <div class="weather-label">${this._t(h.key)}</div>
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
                        ${p.length?this._renderForecastRows(p,e):K}
                    </div>
                </div>
            </ha-card>
        `}getCardSize(){return 5}static getStubConfig(){return{entity:"weather.home"}}},{type:"custom:sem-weather-card",name:"SEM Weather",description:"Lumina-styled clock + weather card with forecast",preview:!1});const bt=[{key:"today",labelKey:"period_today"},{key:"yesterday",labelKey:"period_yesterday"},{key:"week",labelKey:"period_this_week"},{key:"month",labelKey:"period_this_month"},{key:"year",labelKey:"period_this_year"}];ft("sem-period-selector-card",class extends mt{static get watchedEntities(){return[]}constructor(){super(),this._active="week",this._firstRender=!0}setConfig(t){super.setConfig(t),t.default_period&&(this._active=t.default_period)}set hass(t){this._hass,this._hass=t;const e=t?.language,i="function"==typeof semLocalize;(e!==this._lang||i&&!this._localizeReady)&&(this._lang=e,this._localizeReady=i,this.requestUpdate())}get hass(){return this._hass}firstUpdated(){this._dispatchPeriod(this._active)}_getPeriod(t){const e=new Date,i=(t=>new Date(t.getFullYear(),t.getMonth(),t.getDate()))(e);switch(t){case"today":return{start:i,end:e,granularity:"hour"};case"yesterday":{const t=new Date(i);return t.setDate(t.getDate()-1),{start:t,end:i,granularity:"hour"}}case"week":{const t=e.getDay()||7,s=new Date(i);return s.setDate(s.getDate()-(t-1)),{start:s,end:e,granularity:"day"}}case"month":return{start:new Date(e.getFullYear(),e.getMonth(),1),end:e,granularity:"day"};case"year":return{start:new Date(e.getFullYear(),0,1),end:e,granularity:"month"};default:return this._getPeriod("week")}}_dispatchPeriod(t){this._active=t,this.requestUpdate();const e=this._getPeriod(t);document.dispatchEvent(new CustomEvent("sem-period-change",{detail:{...e,key:t}}))}render(){if(!this._config)return K;const t=this._theme();return H`
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
                    ${bt.map(t=>H`
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
        `}getCardSize(){return 1}static getStubConfig(){return{}}},{type:"custom:sem-period-selector-card",name:"SEM Period Selector",description:"Glassmorphism period picker for SEM chart cards",preview:!1});const $t="sensor.sem_",wt=["flow_solar_to_home_energy","flow_solar_to_ev_energy","daily_co2_avoided","yearly_co2_avoided","lifetime_co2_avoided","yearly_trees_equivalent","lifetime_trees_equivalent"];function kt(t){return wt.map(e=>`${t}${e}`)}ft("sem-energy-impact-card",class extends mt{static get watchedEntities(){return kt($t)}setConfig(t){super.setConfig(t),this._prefix=t.entity_prefix||$t,this._prefix!==$t&&(this._prevVals={})}set hass(t){this._hass,this._hass=t;const e=t?.language,i="function"==typeof semLocalize;let s=!1;if((e!==this._lang||i&&!this._localizeReady)&&(this._lang=e,this._localizeReady=i,s=!0),this._isFrozen()&&!s)return;const r=kt(this._prefix||$t);let a=!1;for(const e of r)if(this._prevVals[e]!==t.states[e]?.state){a=!0;break}if(a||s){for(const e of r)this._prevVals[e]=t.states[e]?.state;this._scheduleUpdate()}}get hass(){return this._hass}_val(t,e=0){return this._state(`${this._prefix||$t}${t}`,e)}_treeIcon(t){return t>=50?"mdi:forest":t>=10?"mdi:pine-tree":t>=1?"mdi:tree":"mdi:sprout"}render(){if(!this._config)return K;const t=this._theme(),e=this._val("flow_solar_to_home_energy")+this._val("flow_solar_to_ev_energy"),i=(.128*e).toFixed(1),s=`${e.toFixed(1)} kWh × 128 g/kWh`,r=this._val("yearly_trees_equivalent"),a=this._val("lifetime_trees_equivalent"),o=this._val("yearly_co2_avoided"),n=this._val("lifetime_co2_avoided"),l=r>=10?r.toFixed(0):r.toFixed(1),c=this._treeIcon(r);return H`
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
                    font-size: 11px;
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
                    font-size: 11px;
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
                    font-size: 10px;
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
        `}getCardSize(){return 3}static getStubConfig(){return{entity_prefix:$t}}},{type:"custom:sem-energy-impact-card",name:"SEM Energy Impact Card",description:"Environmental impact display for Solar Energy Management",preview:!1});const St="daily_ev_energy",Ct="lifetime_ev_energy",Et="lifetime_ev_solar_share",zt="lifetime_ev_cost",Mt="lifetime_ev_sessions",Dt="sensor.sem_";ft("sem-ev-progress-card",class extends mt{static get watchedEntities(){return[`${Dt}${St}`,`${Dt}${Ct}`,`${Dt}${Et}`,`${Dt}${zt}`,`${Dt}${Mt}`,"number.sem_daily_ev_target"]}setConfig(t){super.setConfig(t)}_prefix(){return this._config?.entity_prefix??Dt}_pct(t,e){return e<=0?0:Math.min(100,t/e*100)}_barColor(t,e){return 0===t?"#666":e>=100?"#8DC892":e>=70?"#ff9800":"#f44336"}_fmtEnergy(t){return null==t||isNaN(t)?"—":t.toFixed(t<10?2:1)+" kWh"}_fmtCost(t,e){return null==t||isNaN(t)?"—":t.toFixed(2)+" "+e}_fmtSessions(t){return null==t||isNaN(t)?"—":String(Math.round(t))}render(){if(!this._hass||!this._config)return K;const t=this._theme(),e=this._prefix(),i=this._state(`${e}${St}`),s=this._state("number.sem_daily_ev_target",10),r=this._state(`${e}${Ct}`),a=this._state(`${e}${Et}`),o=this._state(`${e}${zt}`),n=this._state(`${e}${Mt}`),l=_t(this._hass),c=this._pct(i,s),d=this._barColor(s,c),h=s>0?H`<span class="target-pct">${Math.round(c)}% ${this._t("of_target")}</span>`:H`<span class="target-pct no-target">${this._t("no_target")}</span>`,p=["radial-gradient(ellipse 80% 70% at 20% 50%, rgba(141,200,146,0.06) 0%, transparent 70%)",`radial-gradient(circle at 2px 2px, ${t.dotColor} 0.7px, transparent 0.7px)`].join(", ");return H`
            <style>
                :host {
                    display: block;
                    font-family: 'Segoe UI', 'Roboto', sans-serif;
                }

                .card {
                    background: ${t.cardBg};
                    background-image: ${p};
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
                        ${h}
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
        `}getCardSize(){return 3}static getStubConfig(){return{entity_prefix:Dt}}},{type:"sem-ev-progress-card",name:"SEM EV Progress Card",description:"Daily EV progress bar and lifetime charging statistics"});ft("sem-gauge-card",class extends mt{static get watchedEntities(){return[]}setConfig(t){if(!t.entity)throw new Error("sem-gauge-card requires entity");super.setConfig(t),this._entity=t.entity,this._name=t.name||null,this._min=t.min??0,this._max=t.max??100,this._color=t.color||"#4db6ac",this._unit=t.unit||"%"}set hass(t){this._hass,this._hass=t;const e=t?.states[this._entity]?.state;e!==this._lastState&&(this._lastState=e,this.requestUpdate())}get hass(){return this._hass}render(){if(!this._hass||!this._config)return K;const t=this._hass.states[this._entity],e=t&&parseFloat(t.state)||0,i=this._name||t?.attributes?.friendly_name||this._entity,s=Math.min(Math.max((e-this._min)/(this._max-this._min),0),1),r=this._theme(),a=this._color,o=58,n=-210,l=n+240*s,c=t=>{const e=t*Math.PI/180;return{x:70+o*Math.cos(e),y:70+o*Math.sin(e)}},d=c(n),h=c(30),p=c(l),g=240*s>180?1:0,_=s<.5?`color-mix(in srgb, #f44336 ${Math.round(100*(1-2*s))}%, #ff9800)`:`color-mix(in srgb, ${a} ${Math.round(2*(s-.5)*100)}%, #ff9800)`;return H`
            <ha-card>
                <div class="gauge-wrap">
                    <svg viewBox="0 0 140 100" xmlns="http://www.w3.org/2000/svg">
                        <defs>
                            <filter id="glow-${this._entity.replace(/\./g,"_")}" x="-20%" y="-20%" width="140%" height="140%">
                                <feGaussianBlur stdDeviation="3" result="blur"/>
                                <feFlood flood-color="${_}" flood-opacity="0.3"/>
                                <feComposite in2="blur" operator="in"/>
                                <feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge>
                            </filter>
                        </defs>
                        <!-- Background arc -->
                        <path d="M ${d.x} ${d.y} A ${o} ${o} 0 ${1} 1 ${h.x} ${h.y}"
                              fill="none" stroke="${r.surface||"rgba(255,255,255,0.08)"}" stroke-width="8"
                              stroke-linecap="round"/>
                        <!-- Value arc -->
                        ${s>.01?j`
                            <path d="M ${d.x} ${d.y} A ${o} ${o} 0 ${g} 1 ${p.x} ${p.y}"
                                  fill="none" stroke="${_}" stroke-width="8"
                                  stroke-linecap="round"
                                  filter="url(#glow-${this._entity.replace(/\./g,"_")})"
                                  style="transition: d 1s ease"/>
                        `:""}
                    </svg>
                    <div class="gauge-center">
                        <span class="gauge-value" style="color:${_}">${e.toFixed(1)}${this._unit}</span>
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
        `}getCardSize(){return 3}static getStubConfig(){return{entity:"sensor.sem_self_consumption_rate"}}},{type:"custom:sem-gauge-card",name:"SEM Gauge Card",description:"Lumina-styled arc gauge for percentage values",preview:!1});const Ft="sensor.sem_",Tt=["solar_power","daily_solar_energy","monthly_solar_yield_energy","yearly_solar_yield_energy","flow_solar_to_home_power","flow_solar_to_battery_power","flow_solar_to_ev_power","flow_solar_to_grid_power","flow_solar_to_home_energy","flow_solar_to_battery_energy","flow_solar_to_ev_energy","flow_solar_to_grid_energy","forecast_today_kwh","forecast_tomorrow_kwh","forecast_remaining_today_kwh","forecast_peak_power_today_w","forecast_peak_time_today","best_surplus_window","pv_daily_specific_yield","pv_performance_vs_forecast","pv_estimated_annual_degradation","pv_degradation_trend"];function At(t){return Tt.map(e=>`${t}${e}`)}ft("sem-solar-card",class extends mt{static get watchedEntities(){return At(Ft)}setConfig(t){super.setConfig(t),this._prefix=t.entity_prefix||Ft,this._prefix!==Ft&&(this._prevVals={})}set hass(t){this._hass=t;const e=t?.language,i="function"==typeof semLocalize;let s=!1;if((e!==this._lang||i&&!this._localizeReady)&&(this._lang=e,this._localizeReady=i,s=!0),this._isFrozen()&&!s)return;const r=At(this._prefix||Ft);let a=!1;for(const e of r)if(this._prevVals[e]!==t.states[e]?.state){a=!0;break}if(a||s){for(const e of r)this._prevVals[e]=t.states[e]?.state;this._scheduleUpdate()}}get hass(){return this._hass}_val(t,e=0){return this._state(`${this._prefix}${t}`,e)}_valStr(t){return this._stateStr(`${this._prefix}${t}`)}_fmt(t,e=1){return null==t||isNaN(t)?"—":t.toFixed(e)}render(){if(!this._config)return K;const t=this._theme(),e=this._val("solar_power"),i=this._val("daily_solar_energy"),s=this._val("monthly_solar_yield_energy"),r=this._val("yearly_solar_yield_energy"),a=Math.min(Math.max(e/1e4,0),1),o=2*Math.PI*42,n=(o*(1-a)).toFixed(1),l=e>50?"solarPulse 3s ease-in-out infinite":"none",c=this._val("flow_solar_to_home_power"),d=this._val("flow_solar_to_home_energy"),h=this._val("flow_solar_to_battery_power"),p=this._val("flow_solar_to_battery_energy"),g=this._val("flow_solar_to_ev_power"),_=this._val("flow_solar_to_ev_energy"),u=this._val("flow_solar_to_grid_power"),f=this._val("flow_solar_to_grid_energy"),m=this._val("forecast_today_kwh"),v=this._val("forecast_tomorrow_kwh"),y=this._val("forecast_remaining_today_kwh"),x=this._val("forecast_peak_power_today_w"),b=this._valStr("forecast_peak_time_today"),$=this._valStr("best_surplus_window"),w=this._val("pv_daily_specific_yield"),k=this._val("pv_performance_vs_forecast"),S=this._val("pv_estimated_annual_degradation"),C=this._valStr("pv_degradation_trend"),E=0!==k?this._fmt(k,0)+"%":"—",z=k>=0?"#8DC892":"#f06292";return H`
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
                    font-size: 10px; font-weight: 600; text-transform: uppercase;
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
                .flow-label { font-size: 11px; color: var(--secondary-text-color,${t.textSec}); flex: 1; }
                .flow-vals { text-align: right; }
                .flow-power {
                    font-size: 11px; font-weight: 600;
                    font-variant-numeric: tabular-nums;
                    color: var(--primary-text-color,${t.text});
                }
                .flow-energy {
                    font-size: 9px; color: var(--secondary-text-color,${t.textSec});
                    font-variant-numeric: tabular-nums;
                }

                /* ── Two-column section ── */
                .two-col {
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                    gap: 0 20px;
                }
                @media (max-width: 400px) { .two-col { grid-template-columns: 1fr; } }

                /* ── Metric rows ── */
                .metric-row {
                    display: flex; justify-content: space-between; align-items: baseline;
                    padding: 2px 0;
                }
                .metric-label {
                    font-size: 11px; color: var(--secondary-text-color,${t.textSec});
                    font-weight: 500;
                }
                .metric-val {
                    font-size: 12px; font-weight: 600;
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
                    font-size: 10px; color: var(--secondary-text-color,${t.textTertiary});
                    font-weight: 500; margin-bottom: 2px;
                }
                .chip-value {
                    font-size: 13px; font-weight: 600; color: #ff9800;
                    font-variant-numeric: tabular-nums;
                }
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
                                <div class="solar-power-value">${pt(e)}</div>
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
                                    <div class="flow-power">${pt(c)}</div>
                                    <div class="flow-energy">${this._fmt(d,2)} kWh</div>
                                </div>
                            </div>
                            <div class="flow-row">
                                <div class="flow-dot" style="background:#f06292"></div>
                                <span class="flow-label">${this._t("battery")}</span>
                                <div class="flow-vals">
                                    <div class="flow-power">${pt(h)}</div>
                                    <div class="flow-energy">${this._fmt(p,2)} kWh</div>
                                </div>
                            </div>
                            <div class="flow-row">
                                <div class="flow-dot" style="background:#8DC892"></div>
                                <span class="flow-label">${this._t("ev")}</span>
                                <div class="flow-vals">
                                    <div class="flow-power">${pt(g)}</div>
                                    <div class="flow-energy">${this._fmt(_,2)} kWh</div>
                                </div>
                            </div>
                            <div class="flow-row">
                                <div class="flow-dot" style="background:#8353d1"></div>
                                <span class="flow-label">${this._t("grid_export")}</span>
                                <div class="flow-vals">
                                    <div class="flow-power">${pt(u)}</div>
                                    <div class="flow-energy">${this._fmt(f,2)} kWh</div>
                                </div>
                            </div>
                        </div>
                    </div>

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
                                    ${x>0?pt(x):"—"}
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
                                <span class="metric-val">${C||"—"}</span>
                            </div>
                        </div>
                    </div>

                </div>
            </ha-card>
        `}getCardSize(){return 5}static getStubConfig(){return{entity_prefix:Ft}}},{type:"sem-solar-card",name:"SEM Solar",description:"Consolidated solar production card with flows, forecast, and performance metrics"});const It="sensor.sem_",Rt=["solar_power","daily_solar_energy","monthly_solar_yield_energy","forecast_today_kwh","forecast_tomorrow_kwh","self_consumption_rate","autarky_rate","daily_costs","daily_savings","daily_ev_energy","daily_grid_import_energy"];function Nt(t){return Rt.map(e=>`${t}${e}`)}ft("sem-solar-summary-card",class extends mt{static get watchedEntities(){return Nt(It)}setConfig(t){super.setConfig(t),this._prefix=t.entity_prefix||It,this._prefix!==It&&(this._prevVals={})}set hass(t){this._hass=t;const e=t?.language,i="function"==typeof semLocalize;let s=!1;if((e!==this._lang||i&&!this._localizeReady)&&(this._lang=e,this._localizeReady=i,s=!0),this._isFrozen()&&!s)return;const r=Nt(this._prefix||It);let a=!1;for(const e of r)if(this._prevVals[e]!==t.states[e]?.state){a=!0;break}if(a||s){for(const e of r)this._prevVals[e]=t.states[e]?.state;this._scheduleUpdate()}}get hass(){return this._hass}_val(t,e=0){return this._state(`${this._prefix}${t}`,e)}_valStr(t){return this._stateStr(`${this._prefix}${t}`)}_fmt(t,e=1){return null==t||isNaN(t)?"—":t.toFixed(e)}render(){if(!this._config)return K;const t=this._theme(),e=this._val("solar_power"),i=this._val("daily_solar_energy"),s=this._val("monthly_solar_yield_energy"),r=this._val("forecast_today_kwh"),a=this._val("forecast_tomorrow_kwh"),o=this._val("self_consumption_rate"),n=this._val("autarky_rate"),l=this._val("daily_costs"),c=this._val("daily_savings"),d=this._val("daily_ev_energy"),h=this._val("daily_grid_import_energy"),p=_t(this._hass),g=(.15+.6*Math.min(e/1e4,1)).toFixed(3),_=2*Math.PI*42,u=(_*(1-(r>0?Math.min(i/r,1):0))).toFixed(1);return H`
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
                                    style="opacity:${g}">
                                    <animate attributeName="r" values="42;45;42" dur="3s" repeatCount="indefinite"/>
                                    <animate attributeName="opacity" values="${g};${(.4*parseFloat(g)).toFixed(3)};${g}" dur="3s" repeatCount="indefinite"/>
                                </circle>
                                <circle class="ring-bg" cx="50" cy="50" r="42"/>
                                <circle class="progress-arc" cx="50" cy="50" r="42"
                                    stroke-dasharray="${_.toFixed(1)}"
                                    style="stroke-dashoffset:${u}"/>
                            </svg>
                            <div class="ring-icon">
                                <div class="power">${pt(e)}</div>
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
                                <span class="hero-value c-grid">${this._fmt(h,2)} kWh</span>
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
                            <div class="metric-value c-cost">${this._fmt(l,2)} ${p}</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">${this._t("saved")}</div>
                            <div class="metric-value c-savings">${this._fmt(c,2)} ${p}</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">${this._t("monthly")}</div>
                            <div class="metric-value c-solar">${this._fmt(s,1)} kWh</div>
                        </div>
                    </div>

                </div>
            </ha-card>
        `}getCardSize(){return 4}static getStubConfig(){return{entity_prefix:It}}},{type:"sem-solar-summary-card",name:"SEM Solar Summary",description:"Lumina-styled solar overview with glow ring and production metrics"});const Ot="sensor.sem_",Pt=["battery_soc","battery_power","battery_charge_power","battery_discharge_power","battery_status","battery_health_score","battery_cycles_estimated","battery_temperature","battery_session_type","battery_session_energy","battery_session_solar_share","battery_session_duration","battery_session_avg_power","battery_session_cost","battery_session_savings","daily_battery_charge_energy","daily_battery_discharge_energy","daily_battery_savings","flow_solar_to_battery_energy","flow_grid_to_battery_energy","monthly_battery_charge_energy","monthly_battery_discharge_energy"];ft("sem-battery-card",class extends mt{static get watchedEntities(){return Pt.map(t=>`${Ot}${t}`)}setConfig(t){super.setConfig(t),this._prefix=t.entity_prefix||Ot}set hass(t){this._hass=t;const e=t?.language,i="function"==typeof semLocalize;let s=!1;if((e!==this._lang||i&&!this._localizeReady)&&(this._lang=e,this._localizeReady=i,s=!0),this._isFrozen()&&!s)return;const r=t?.states[`${this._prefix}battery_status`]?.state;if(("unavailable"===r||"unknown"===r)&&!s)return;const a=Pt.map(e=>t?.states[`${this._prefix}${e}`]?.state||"").join(",")+"|"+e;(a!==this._lastBattKey||s)&&(this._lastBattKey=a,this._scheduleUpdate())}get hass(){return this._hass}_val(t,e=0){return this._state(`${this._prefix}${t}`,e)}_valStr(t){return this._stateStr(`${this._prefix}${t}`)}_fmt(t,e=1){return null==t||isNaN(t)?"—":t.toFixed(e)}render(){if(!this._hass||!this._config)return K;const t=this._theme(),e=2*Math.PI*42,i=e.toFixed(1),s=this._val("battery_soc",0),r=this._val("battery_power",0),a=this._val("battery_charge_power",0),o=this._val("battery_discharge_power",0),n=this._valStr("battery_status"),l=this._val("battery_health_score",0),c=this._val("battery_cycles_estimated",0),d=this._val("daily_battery_charge_energy",0),h=this._val("daily_battery_discharge_energy",0),p=this._val("daily_battery_savings",0),g=this._val("monthly_battery_charge_energy",0),_=this._val("monthly_battery_discharge_energy",0),u=this._val("flow_solar_to_battery_energy",0),f=_t(this._hass),m=this._hass?.states[`${this._prefix}battery_temperature`],v=m&&"unavailable"!==m.state&&"unknown"!==m.state?parseFloat(m.state):null,y="charging"===n||a>10,x="discharging"===n||o>10,b=y?this._t("charging"):x?this._t("discharging"):this._t("idle"),$=y?"#f06292":"#4db6ac",w=y?"#f06292":x?"#4db6ac":t.textSec||"#888",k=y||x?"0.5":"0.2",S=y||x?"socPulse 2s ease-in-out infinite":"none",C=(e*(1-Math.min(Math.max(s/100,0),1))).toFixed(1),E=d>0?Math.round(u/d*100):0,z=this._valStr("battery_session_type"),M="charge"===z||"discharge"===z,D="charge"===z,F=M?this._val("battery_session_energy",0):0,T=M?this._val("battery_session_duration",0):0,A=M?this._val("battery_session_avg_power",0):0,I=M?this._val("battery_session_solar_share",0):0,R=M?this._val("battery_session_cost",0):0,N=M?this._val("battery_session_savings",0):0,O=D?"#f06292":"#4db6ac";t.dotColor;const P=t.surface||"rgba(255,255,255,0.06)",B=t.surfaceBorder||"rgba(255,255,255,0.05)",L=t.surfaceHover||"rgba(255,255,255,0.12)",U=t.textSec||"#999",W=t.textTertiary||"#888";return H`
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
                    display: flex; justify-content: space-between; align-items: baseline; padding: 2px 0;
                }
                .metric-label { font-size: 12px; color: var(--secondary-text-color, ${U}); font-weight: 500; }
                .metric-val { font-size: 13px; font-weight: 600; font-variant-numeric: tabular-nums; color: #4db6ac; }
                .chips { display: flex; gap: 8px; margin-top: 14px; flex-wrap: wrap; }
                .chip {
                    flex: 1; min-width: 80px;
                    background: var(--secondary-background-color, ${P});
                    border: 1px solid var(--divider-color, ${B});
                    border-radius: 10px; padding: 8px 10px; text-align: center;
                    transition: border-color 0.3s cubic-bezier(0.4,0,0.2,1);
                }
                .chip:hover { border-color: var(--divider-color, ${L}); }
                .chip-label {
                    font-size: 10px; color: var(--secondary-text-color, ${W});
                    font-weight: 500; letter-spacing: 0.3px; margin-bottom: 3px;
                }
                .chip-value { font-size: 13px; font-weight: 600; font-variant-numeric: tabular-nums; }
                .c-charge { color: #f06292; }
                .c-discharge { color: #4db6ac; }
                .c-savings { color: #8DC892; }
                .chip-src { font-size: 9px; color: var(--secondary-text-color, ${W}); margin-top: 1px; }
                .session-section {
                    margin-top: 14px; padding: 10px 12px;
                    background: var(--secondary-background-color, ${P});
                    border: 1px solid var(--divider-color, ${B});
                    border-radius: 10px;
                }
                .sess-header { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
                .sess-title {
                    font-size: 12px; font-weight: 600;
                    text-transform: uppercase; letter-spacing: 0.5px;
                }
                .sess-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 4px; }
                .sess-item-label { font-size: 10px; color: var(--secondary-text-color, ${W}); }
                .sess-item-value {
                    font-size: 12px; font-weight: 600; font-variant-numeric: tabular-nums;
                    color: var(--primary-text-color, ${t.text||"#e0e0e0"});
                }
                .monthly-section { display: flex; gap: 8px; margin-top: 10px; }
                .month-chip {
                    flex: 1; text-align: center; padding: 6px 8px;
                    background: var(--secondary-background-color, ${P});
                    border: 1px solid var(--divider-color, ${B});
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
                                <span class="metric-val">${pt(r)}</span>
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
                            <div class="metric-row">
                                <span class="metric-label">${this._t("temperature")}</span>
                                <span class="metric-val">
                                    ${null!=v?`${this._fmt(v,1)}°C`:"—"}
                                </span>
                            </div>
                        </div>
                    </div>

                    <div class="session-section">
                        <div class="sess-header">
                            <ha-icon icon="mdi:battery-sync"
                                style="--mdc-icon-size:14px;color:${M?O:t.textSec}">
                            </ha-icon>
                            <span class="sess-title" style="color:${M?O:t.textSec}">
                                ${M?D?this._t("charging"):this._t("discharging"):this._t("idle")}
                            </span>
                        </div>
                        ${M?H`
                        <div class="sess-grid">
                            <div>
                                <div class="sess-item-label">${this._t("energy")}</div>
                                <div class="sess-item-value">${this._fmt(F,2)} kWh</div>
                            </div>
                            <div>
                                <div class="sess-item-label">${this._t("duration")}</div>
                                <div class="sess-item-value">${Math.round(T)} min</div>
                            </div>
                            <div>
                                <div class="sess-item-label">${this._t("avg_power")}</div>
                                <div class="sess-item-value">${pt(A)}</div>
                            </div>
                            <div>
                                <div class="sess-item-label">${this._t("source")}</div>
                                <div class="sess-item-value">
                                    ${D?`${this._t("solar")}: ${this._fmt(I,0)}%`:""}
                                </div>
                            </div>
                            <div>
                                <div class="sess-item-label">${this._t("cost")}</div>
                                <div class="sess-item-value">
                                    ${D?`${this._fmt(R,2)} ${f}`:`${this._t("saved")} ${this._fmt(N,2)} ${f}`}
                                </div>
                            </div>
                        </div>
                        `:H``}
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
                            <div class="chip-value c-discharge">${this._fmt(h,2)} kWh</div>
                        </div>
                        <div class="chip">
                            <div class="chip-label">${this._t("savings_today")}</div>
                            <div class="chip-value c-savings">
                                ${this._fmt(p,2)} ${f}
                            </div>
                        </div>
                    </div>

                    <div class="monthly-section">
                        <div class="month-chip">
                            <div class="chip-label">
                                ${this._t("monthly")} ${this._t("charge")}
                            </div>
                            <div class="chip-value c-charge">${this._fmt(g,1)} kWh</div>
                        </div>
                        <div class="month-chip">
                            <div class="chip-label">
                                ${this._t("monthly")} ${this._t("discharge")}
                            </div>
                            <div class="chip-value c-discharge">${this._fmt(_,1)} kWh</div>
                        </div>
                    </div>
                </div>
            </ha-card>
        `}getCardSize(){return 3}static getStubConfig(){return{}}},{type:"sem-battery-card",name:"SEM Battery",description:"Lumina-styled battery hero card with SOC arc ring and key metrics"});const Bt="sensor.sem_",Lt=["grid_power","grid_import_power","grid_export_power","grid_status","daily_grid_import_energy","daily_grid_export_energy","monthly_grid_import_energy","monthly_grid_export_energy","consecutive_peak_15min","monthly_consecutive_peak","current_vs_peak_percentage","target_peak_limit","peak_margin","peak_trend","load_management_status","loads_currently_shed","available_load_reduction","controllable_devices_count","tariff_current_import_rate","tariff_current_export_rate","tariff_price_level","tariff_today_min_price","tariff_today_max_price","surplus_total_w","surplus_unallocated_w","surplus_active_devices","surplus_total_devices"];ft("sem-grid-card",class extends mt{static get watchedEntities(){return Lt.map(t=>`${Bt}${t}`)}setConfig(t){super.setConfig(t),this._prefix=t.entity_prefix||Bt}set hass(t){this._hass=t;const e=t?.language,i="function"==typeof semLocalize;let s=!1;if((e!==this._lang||i&&!this._localizeReady)&&(this._lang=e,this._localizeReady=i,s=!0),this._isFrozen()&&!s)return;const r=Lt.map(e=>t?.states[`${this._prefix}${e}`]?.state||"").join(",")+"|"+e;(r!==this._lastGridKey||s)&&(this._lastGridKey=r,this._scheduleUpdate())}get hass(){return this._hass}_val(t,e=0){return this._state(`${this._prefix}${t}`,e)}_valStr(t){return this._stateStr(`${this._prefix}${t}`)}_fmt(t,e=1){return null==t||isNaN(t)?"—":t.toFixed(e)}_peakColor(t){return t>=90?"#f06292":t>=70?"#ff9800":"#8DC892"}_priceLevelColor(t){return"high"===t?"#f06292":"low"===t?"#8DC892":"—"!==t?"#ff9800":"#888"}_section(t,e,i){return H`
            <div class="section">
                <div class="section-title" style="color:${e}">${this._t(t)}</div>
                ${i}
            </div>
        `}_metricRow(t,e){return H`
            <div class="metric-row">
                <span class="metric-label">${this._t(t)}</span>
                <span class="metric-val">${e}</span>
            </div>
        `}render(){if(!this._hass||!this._config)return K;const t=this._theme(),e=_t(this._hass),i=this._val("grid_import_power"),s=this._val("grid_export_power"),r=s>i&&s>10,a=i>10,o=r?"mdi:transmission-tower-export":"mdi:transmission-tower-import",n=r?"#8353d1":"#488fc2",l=a||r?"0.45":"0.1",c=this._valStr("grid_status"),d=""!==c&&"—"!==c?c:r?this._t("exporting"):a?this._t("importing"):this._t("idle"),h=r?"#8353d1":a?"#488fc2":"#888",p=this._val("daily_grid_import_energy"),g=this._val("daily_grid_export_energy"),_=p-g,u=_<=0?"#8353d1":"#488fc2",f=this._val("current_vs_peak_percentage"),m=this._val("consecutive_peak_15min"),v=this._val("monthly_consecutive_peak"),y=this._val("target_peak_limit"),x=this._val("peak_margin"),b=this._valStr("peak_trend"),$=this._peakColor(f),w=x>0?"#8DC892":"#f06292",k=(200*Math.min(Math.max(f/100,0),1)).toFixed(1),S=this._valStr("load_management_status"),C=this._val("loads_currently_shed"),E=this._val("available_load_reduction"),z=this._val("controllable_devices_count"),M=this._val("tariff_current_import_rate"),D=this._val("tariff_current_export_rate"),F=this._valStr("tariff_price_level"),T=this._val("tariff_today_min_price"),A=this._val("tariff_today_max_price"),I=this._priceLevelColor(F),R=this._val("surplus_total_w"),N=this._val("surplus_unallocated_w"),O=Math.max(0,R-N),P=this._val("surplus_active_devices"),B=this._val("surplus_total_devices");t.dotColor;const L=t.textSec||"#999",U=t.surface||"rgba(255,255,255,0.06)",W=t.surfaceBorder||"rgba(255,255,255,0.12)";return H`
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
                    font-size: 10px; text-transform: uppercase; letter-spacing: 0.4px;
                    color: var(--secondary-text-color, ${L}); margin-bottom: 1px;
                }
                .hero-pw-val { font-size: 17px; font-weight: 700; font-variant-numeric: tabular-nums; }
                .hero-pw-val.import { color: #488fc2; }
                .hero-pw-val.export { color: #8353d1; }
                .hero-status {
                    font-size: 11px; font-weight: 500;
                    text-transform: uppercase; letter-spacing: 0.5px;
                }
                .section {
                    margin-top: 10px; padding: 10px 12px;
                    background: var(--secondary-background-color, ${U});
                    border: 1px solid var(--divider-color, ${W});
                    border-radius: 10px;
                }
                .section-title {
                    font-size: 10px; font-weight: 600; text-transform: uppercase;
                    letter-spacing: 0.6px; margin-bottom: 6px;
                }
                .metric-row {
                    display: flex; justify-content: space-between; align-items: baseline; padding: 2px 0;
                }
                .metric-label {
                    font-size: 11px; color: var(--secondary-text-color, ${L}); font-weight: 500;
                }
                .metric-val {
                    font-size: 12px; font-weight: 600; font-variant-numeric: tabular-nums;
                    color: var(--primary-text-color, ${t.text||"#e0e0e0"});
                }
                .net-row {
                    margin-top: 4px; padding-top: 4px;
                    border-top: 1px solid var(--divider-color, ${W});
                }
                .peak-bar-wrap { margin: 6px 0 4px; position: relative; }
                .peak-bar-bg { width: 100%; height: 8px; fill: rgba(72,143,194,0.12); }
                .peak-bar-fill {
                    height: 8px;
                    transition: width 0.8s cubic-bezier(0.4,0,0.2,1), fill 0.4s ease;
                }
                .peak-bar-svg { width: 100%; height: 8px; display: block; }
                .peak-pct-label {
                    font-size: 11px; font-weight: 700; font-variant-numeric: tabular-nums;
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
                                        ${a?pt(i):"—"}
                                    </span>
                                </div>
                                <div class="hero-pw">
                                    <span class="hero-pw-label">${this._t("export")}</span>
                                    <span class="hero-pw-val export">
                                        ${r?pt(s):"—"}
                                    </span>
                                </div>
                            </div>
                            <div class="hero-status" style="color:${h}">${d}</div>
                        </div>
                    </div>

                    <!-- Today -->
                    <div class="section">
                        <div class="section-title" style="color:#488fc2">${this._t("today")}</div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("import")}</span>
                            <span class="metric-val c-import">${this._fmt(p,2)} kWh</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("export")}</span>
                            <span class="metric-val c-export">${this._fmt(g,2)} kWh</span>
                        </div>
                        <div class="metric-row net-row">
                            <span class="metric-label"><strong>${this._t("net")}</strong></span>
                            <span class="metric-val" style="color:${u}">
                                ${this._fmt(Math.abs(_),2)} kWh
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
                            <span class="metric-val">${pt(m)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("monthly_peak")}</span>
                            <span class="metric-val">${pt(v)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("peak_limit")}</span>
                            <span class="metric-val">${pt(y)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("peak_margin")}</span>
                            <span class="metric-val" style="color:${w}">
                                ${pt(x)}
                            </span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("trend")}</span>
                            <span class="metric-val">${b||"—"}</span>
                        </div>
                    </div>

                    <!-- Load Control -->
                    <div class="section">
                        <div class="section-title" style="color:#488fc2">${this._t("load_control")}</div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("status")}</span>
                            <span class="metric-val">${S||"—"}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("loads_shed")}</span>
                            <span class="metric-val">${this._fmt(C,0)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("available_reduction")}</span>
                            <span class="metric-val">${pt(E)}</span>
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
                            <span class="metric-val" style="color:${I}">
                                ${F||"—"}
                            </span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("today_min")}</span>
                            <span class="metric-val c-green">
                                ${0!==T?this._fmt(T,4):"—"}
                            </span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("today_max")}</span>
                            <span class="metric-val c-solar">
                                ${0!==A?this._fmt(A,4):"—"}
                            </span>
                        </div>
                    </div>

                    <!-- Surplus -->
                    <div class="section">
                        <div class="section-title" style="color:#488fc2">${this._t("surplus")}</div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("total_surplus")}</span>
                            <span class="metric-val c-solar">${pt(R)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("allocated")}</span>
                            <span class="metric-val">${pt(O)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("unallocated")}</span>
                            <span class="metric-val c-green">${pt(N)}</span>
                        </div>
                        <div class="metric-row">
                            <span class="metric-label">${this._t("active_devices")}</span>
                            <span class="metric-val">
                                ${Math.round(P)} / ${Math.round(B)}
                            </span>
                        </div>
                    </div>
                </div>
            </ha-card>
        `}getCardSize(){return 5}static getStubConfig(){return{entity_prefix:Bt}}},{type:"sem-grid-card",name:"SEM Grid",description:"Consolidated grid card with import/export, peak management, load control, tariff, and surplus"});const Ut="sensor.sem_",Wt=20;function Ht(t){return 36+556*t}function jt(t){if(!t||"string"!=typeof t)return null;const e=t.match(/^(\d{1,2}):(\d{2})$/);if(!e)return null;const i=parseInt(e[1],10),s=parseInt(e[2],10);return i>24||s>59?null:(i+s/60)/24}function Gt(t){if(!Array.isArray(t))return[];const e=[];let i=-1;for(let s=0;s<24;s++)t[s]&&-1===i?i=s:t[s]||-1===i||(e.push({start:i/24,end:s/24}),i=-1);return-1!==i&&e.push({start:i/24,end:1}),e}ft("sem-schedule-card",class extends mt{static get watchedEntities(){return[`${Ut}tariff_price_level`,`${Ut}night_start_time`,`${Ut}night_end_time`,`${Ut}best_surplus_window`,`${Ut}predicted_surplus_window`,`${Ut}ev_power`,`${Ut}charging_state`,`${Ut}surplus_total_w`]}setConfig(t){super.setConfig(t),this._prefix=t.entity_prefix||Ut}set hass(t){this._hass=t;const e=t?.language,i="function"==typeof semLocalize;let s=!1;if((e!==this._lang||i&&!this._localizeReady)&&(this._lang=e,this._localizeReady=i,s=!0),this._isFrozen()&&!s)return;const r=["tariff_price_level","night_start_time","night_end_time","best_surplus_window","predicted_surplus_window","ev_power","charging_state"].map(e=>{const i=t?.states[`${this._prefix}${e}`];return(i?.state||"")+JSON.stringify(i?.attributes?.tariff_schedule_today||"")+JSON.stringify(i?.attributes?.schedule_surplus_hours||"")+JSON.stringify(i?.attributes?.schedule_ev_hours||"")}),a=r.join("|")+"|"+e;(a!==this._lastSchedKey||s)&&(this._lastSchedKey=a,this._scheduleUpdate())}get hass(){return this._hass}_stateObj(t){return this._hass?.states[`${this._prefix}${t}`]||null}_getTariffSchedule(){const t=this._stateObj("tariff_price_level"),e=t?.attributes?.tariff_schedule_today;if(Array.isArray(e)&&e.length>0)return e.map(t=>({start:jt(t.start)??0,end:jt(t.end)??1,type:(t.tariff||t.type||"HT").toUpperCase()}));const i=(new Date).getDay();return 0===i||6===i?[{start:0,end:1,type:"NT"}]:[{start:0,end:7/24,type:"NT"},{start:7/24,end:20/24,type:"HT"},{start:20/24,end:1,type:"NT"}]}_getNightWindow(){const t=jt(this._stateObj("night_start_time")?.state),e=jt(this._stateObj("night_end_time")?.state);return null==t||null==e?null:{start:t,end:e}}_getPredictedSurplusWindow(){for(const t of["predicted_surplus_window","best_surplus_window"]){const e=this._stateObj(t)?.state;if(!e||"unknown"===e||"unavailable"===e)continue;if(e.toLowerCase().startsWith("tomorrow"))continue;const i=e.split(/[-–]/);if(2!==i.length)continue;const s=jt(i[0].trim()),r=jt(i[1].trim());if(null!=s&&null!=r)return{start:s,end:r}}return null}_getSurplusBlocks(){const t=this._hass?.states[`${this._prefix}surplus_total_w`];return Gt(t?.attributes?.schedule_surplus_hours)}_getEvBlocks(){const t=this._hass?.states[`${this._prefix}surplus_total_w`];return Gt(t?.attributes?.schedule_ev_hours)}_isEvCharging(){const t=parseFloat(this._stateObj("ev_power")?.state);if(!isNaN(t)&&t>10)return!0;const e=this._stateObj("charging_state")?.state;return e&&"charging"===e.toLowerCase()}_buildSvgContent(t){const e=dt,i=t.textSec||"#888",s=t.textTertiary||"#777",r=t.surface||"rgba(255,255,255,0.03)";let a="";for(let t=0;t<=24;t+=2){const e=Ht(t/24);a+=`<text x="${e}" y="12" text-anchor="middle" fill="${i}"\n                font-size="9" font-family="'Segoe UI','Roboto',sans-serif"\n                font-variant-numeric="tabular-nums">${t.toString().padStart(2,"0")}</text>`}[this._t("tariff"),this._t("night"),this._t("surplus"),this._t("ev")].forEach((t,e)=>{a+=`<text x="32" y="${Wt+22*e+9+3.5}" text-anchor="end" fill="${s}"\n                font-size="9" font-family="'Segoe UI','Roboto',sans-serif">${t}</text>`});for(let t=0;t<4;t++){a+=`<rect x="36" y="${Wt+22*t}" width="556" height="18" rx="3" fill="${r}"/>`}for(const t of this._getTariffSchedule()){const i=Ht(t.start),s=Ht(t.end)-i,r="HT"===t.type?e.solar:"#66bb6a",o="HT"===t.type?.7:.55;if(a+=`<rect x="${i}" y="20" width="${s}" height="18"\n                rx="3" fill="${r}" opacity="${o}"/>`,s>30){const e=this._t(t.type.toLowerCase());a+=`<text x="${i+s/2}" y="32.5" text-anchor="middle"\n                    fill="rgba(255,255,255,0.85)" font-size="8" font-weight="600"\n                    font-family="'Segoe UI','Roboto',sans-serif">${e}</text>`}}const o=this._getNightWindow();if(o)if(o.start>o.end){const t=Ht(o.start);a+=`<rect x="${t}" y="42" width="${Ht(1)-t}"\n                    height="18" rx="3" fill="#42a5f5" opacity="0.55"/>`,a+=`<rect x="${Ht(0)}" y="42"\n                    width="${Ht(o.end)-Ht(0)}" height="18"\n                    rx="3" fill="#42a5f5" opacity="0.55"/>`}else{const t=Ht(o.start),e=Ht(o.end)-t;a+=`<rect x="${t}" y="42" width="${e}" height="18"\n                    rx="3" fill="#42a5f5" opacity="0.55"/>`}const n=this._getPredictedSurplusWindow();if(n){const t=Ht(n.start),e=Math.max(0,Ht(n.end)-t);a+=`<rect x="${t}" y="64" width="${e}" height="18"\n                rx="3" fill="#fdd835" opacity="0.18"/>`}for(const t of this._getSurplusBlocks()){const e=Ht(t.start),i=Math.max(0,Ht(t.end)-e);a+=`<rect x="${e}" y="64" width="${i}" height="18"\n                rx="3" fill="#fdd835" opacity="0.6"/>`}for(const t of this._getEvBlocks()){const i=Ht(t.start),s=Math.max(0,Ht(t.end)-i);a+=`<rect x="${i}" y="86" width="${s}" height="18"\n                rx="3" fill="${e.ev}" opacity="0.55"/>`}if(this._isEvCharging()){const t=new Date,i=(t.getHours()+t.getMinutes()/60)/24,s=.5/24,r=Math.max(0,i-s),o=Math.min(1,i+s),n=Ht(r),l=Ht(o)-n;a+=`<rect x="${n}" y="86" width="${l}" height="18"\n                rx="3" fill="${e.ev}" opacity="0.85"/>`}const l=new Date,c=Ht((l.getHours()+l.getMinutes()/60)/24);return a+=`<line x1="${c}" y1="18" x2="${c}" y2="104"\n            stroke="#ef5350" stroke-width="1.5" stroke-linecap="round" opacity="0.9"/>`,a+=`<polygon points="${c-3},18 ${c+3},18 ${c},22"\n            fill="#ef5350" opacity="0.9"/>`,a}render(){if(!this._hass||!this._config)return K;const t=this._theme(),e=t.dotColor||"rgba(128,128,128,0.04)",i=this._buildSvgContent(t);return H`
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
                </div>
            </ha-card>
        `}getCardSize(){return 2}static getStubConfig(){return{}}},{type:"sem-schedule-card",name:"SEM Schedule",description:"24-hour timeline showing tariff, night window, surplus window, and EV charging periods"});const Kt=[{id:"autostart",entity:"number.sem_battery_auto_start_soc",icon:"mdi:play-circle",labelKey:"auto_start_soc",color:"#4db6ac"},{id:"buffer",entity:"number.sem_battery_buffer_soc",icon:"mdi:shield-half-full",labelKey:"buffer_soc",color:"#ff9800"},{id:"floor",entity:"number.sem_battery_assist_floor_soc",icon:"mdi:arrow-collapse-down",labelKey:"assist_floor",color:"#488fc2"},{id:"priority",entity:"number.sem_battery_priority_soc",icon:"mdi:shield-alert",labelKey:"priority_soc",color:"#f44336"}];ft("sem-battery-zones-card",class extends mt{static get watchedEntities(){return Kt.map(t=>t.entity)}setConfig(t){super.setConfig(t)}_getDecimalsForZone(t){const e=this._hass?.states[t];return(e&&parseFloat(e.attributes.step)||1)<1?1:0}_renderZoneMarkers(t){return Kt.map(e=>{const i=this._state(e.entity);return H`
                <div class="zone-marker" style="left:${i}%">
                    <div class="zone-dot" style="background:${e.color};border-color:${t.isDark?"#1e232d":"#fff"}"></div>
                    <span class="zone-marker-label">${i.toFixed(0)}%</span>
                </div>
            `})}_renderStepper(t,e){const i=this._state(t.entity),s=this._getDecimalsForZone(t.entity),r=this._t(t.labelKey);return H`
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
        `}render(){if(!this._config)return K;const t=this._theme(),e=this._state(Kt[0].entity),i=this._state(Kt[1].entity),s=this._state(Kt[3].entity),r=`${this._t("auto_start_soc")} ${e.toFixed(0)}% · Buffer ${i.toFixed(0)}% · ${this._t("priority_soc")} ${s.toFixed(0)}%`;return H`
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
                    font-size: 11px;
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
                @media (max-width: 480px) {
                    .stepper-grid { grid-template-columns: 1fr; }
                }
            </style>
            <div class="wrap">
                <div class="header">
                    <ha-icon icon="mdi:battery-charging-medium" style="--mdc-icon-size:18px;color:#4db6ac"></ha-icon>
                    <span class="header-title">${this._t("soc_zones")}</span>
                    <span class="subtitle">${r}</span>
                </div>
                <div class="zone-bar-wrap">
                    <div class="zone-bar">
                        ${this._renderZoneMarkers(t)}
                    </div>
                </div>
                <div class="stepper-grid">
                    ${Kt.map(e=>this._renderStepper(e,t))}
                </div>
            </div>
        `}getCardSize(){return 4}static getStubConfig(){return{}}},{type:"custom:sem-battery-zones-card",name:"SEM Battery Zones Card",description:"SOC zone configuration for Solar Energy Management",preview:!1});const qt="sensor.sem_",Vt=["daily_costs","daily_savings","daily_export_revenue","daily_battery_savings","daily_net_cost","monthly_costs","monthly_savings","monthly_export_revenue","monthly_net_cost","monthly_battery_savings","yearly_costs","yearly_savings","yearly_export_revenue","yearly_net_cost","yearly_battery_savings","lifetime_total_savings","roi_percentage","roi_payback_years","roi_annual_savings","daily_co2_avoided","yearly_co2_avoided","lifetime_co2_avoided","yearly_trees_equivalent","lifetime_trees_equivalent"];ft("sem-costs-card",class extends mt{static get watchedEntities(){return Vt.map(t=>`${qt}${t}`)}setConfig(t){super.setConfig(t),this._prefix=t.entity_prefix||qt}_val(t,e=0){const i=this._hass?.states[`${this._prefix}${t}`];return i&&"unavailable"!==i.state&&"unknown"!==i.state?parseFloat(i.state)??e:e}_fmt(t,e=2){return null==t||isNaN(t)?"—":t.toFixed(e)}_fmtCurr(t,e,i=2){return null==t||isNaN(t)?"—":t.toFixed(i)+" "+e}_netColor(t){return t<=0?"#8DC892":"#f06292"}_renderPeriodSection(t,e,i,s,r){const a=this._val(`${t}_costs`),o=this._val(`${t}_savings`),n=this._val(`${t}_battery_savings`),l=this._val(`${t}_export_revenue`),c=this._val(`${t}_net_cost`),d=this._netColor(c);return H`
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
        `}render(){if(!this._config||!this._hass)return K;const t=_t(this._hass),e=this._theme(),i=this._val("daily_net_cost"),s=i<=0,r=s?"#8DC892":"#f06292",a=(s?"+":"")+this._fmt(Math.abs(i),2)+" "+t,o=s?this._t("net_saving_today"):this._t("net_cost_today"),n=this._val("roi_percentage"),l=n>=0?"#8DC892":"#f06292",c=this._val("roi_payback_years");return H`
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
                font-size: 11px; font-weight: 500; text-transform: uppercase;
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
                font-size: 10px; font-weight: 600; text-transform: uppercase;
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
                font-size: 11px; color: var(--secondary-text-color, #999);
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
        `}getCardSize(){return 5}static getStubConfig(){return{entity_prefix:"sensor.sem_"}}},{type:"sem-costs-card",name:"SEM Costs",description:"Consolidated financial card with daily/monthly/yearly costs, savings, ROI, and environmental impact"});const Yt="sensor.sem_",Xt=[{id:"ev_econ",icon:"mdi:car-electric",color:"#8DC892",titleKey:"ev_charging_economics"},{id:"investment",icon:"mdi:bank",color:"#96CAEE",titleKey:"system_investment_cost"},{id:"demand",icon:"mdi:flash-triangle",color:"#ff9800",titleKey:"demand_charge"},{id:"tariff",icon:"mdi:tag-multiple",color:"#488fc2",titleKey:"tariff_rates"}];ft("sem-costs-detail-card",class extends mt{static get watchedEntities(){return[`${Yt}lifetime_ev_energy`,`${Yt}lifetime_ev_cost`,`${Yt}lifetime_ev_solar_share`,"number.sem_system_investment_cost",`${Yt}monthly_consecutive_peak`,`${Yt}power_charge_cost`,"number.sem_demand_charge_rate",`${Yt}tariff_current_import_rate`,`${Yt}tariff_current_export_rate`,`${Yt}tariff_price_level`,"number.sem_electricity_import_rate","number.sem_electricity_export_rate"]}constructor(){super(),this._collapsed={}}setConfig(t){super.setConfig(t),this._prefix=t.entity_prefix||Yt}_val(t,e=0){const i=this._hass?.states[`${this._prefix}${t}`];return i&&"unavailable"!==i.state&&"unknown"!==i.state?parseFloat(i.state)??e:e}_valStr(t){const e=this._hass?.states[`${this._prefix}${t}`];return e&&"unavailable"!==e.state&&"unknown"!==e.state?e.state:""}_numVal(t,e=0){const i=this._frozenEntities[t];if(i)return i.value;const s=this._hass?.states[t];return s&&"unavailable"!==s.state&&"unknown"!==s.state?parseFloat(s.state)??e:e}_entityExists(t){const e=this._hass?.states[t];return!(!e||"unavailable"===e.state||"unknown"===e.state)}_toggleSection(t){this._collapsed={...this._collapsed,[t]:!this._collapsed[t]},this.requestUpdate()}_sectionSubtitle(t,e){if("ev_econ"===t){const t=this._val("lifetime_ev_energy");if(t<=0)return this._t("no_ev_data");const i=this._val("lifetime_ev_cost"),s=this._val("lifetime_ev_solar_share");return`${(t>0?i/t:0).toFixed(2)} ${e}/kWh · ${s.toFixed(0)}% solar`}if("investment"===t){const t=this._numVal("number.sem_system_investment_cost");return t>0?`${t.toFixed(0)} ${e}`:""}if("demand"===t){const t=this._val("monthly_consecutive_peak"),i=this._val("power_charge_cost");return`${t.toFixed(1)} kW · ${i.toFixed(2)} ${e}`}if("tariff"===t){const t=this._val("tariff_current_import_rate"),i=this._valStr("tariff_price_level");return i?`${t.toFixed(4)} ${e} · ${i}`:`${t.toFixed(4)} ${e}`}return""}_renderStepper(t,e){const i=this._hass?.states[t],s=this._numVal(t),r=i&&parseFloat(i.attributes.step)||1,a=i?.attributes?.unit_of_measurement||"",o=r<1?2:0,n=s.toFixed(o)+(a?" "+a:"");return H`
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
        `}_renderInfoTile(t,e,i,s){return H`
            <div class="info-tile">
                <ha-icon icon="${t}" style="--mdc-icon-size:18px;color:${e}"></ha-icon>
                <div class="info-tile-content">
                    <span class="info-tile-label">${this._t(i)}</span>
                    <span class="info-tile-value">${s}</span>
                </div>
            </div>
        `}_renderSectionBody(t,e){if("ev_econ"===t){const t=this._val("lifetime_ev_energy");if(!(t>0))return H`<div class="info-empty">${this._t("no_ev_data")}</div>`;const i=this._val("lifetime_ev_cost"),s=this._val("lifetime_ev_solar_share"),r=i/t;return H`
                <div class="info-tiles">
                    ${this._renderInfoTile("mdi:currency-usd","#8DC892","cost_per_kwh",r.toFixed(4)+" "+e+"/kWh")}
                    ${this._renderInfoTile("mdi:solar-power","#ff9800","solar_share",s.toFixed(1)+"%")}
                </div>
            `}if("investment"===t)return H`${this._renderStepper("number.sem_system_investment_cost","system_investment_cost")}`;if("demand"===t){const t=this._val("monthly_consecutive_peak"),i=this._val("power_charge_cost");return H`
                <div class="info-tiles">
                    ${this._renderInfoTile("mdi:chart-bell-curve","#ff9800","monthly_peak",t.toFixed(2)+" kW")}
                    ${this._renderInfoTile("mdi:currency-usd","#f06292","demand_charge",i.toFixed(2)+" "+e)}
                </div>
                ${this._renderStepper("number.sem_demand_charge_rate","demand_charge_rate")}
            `}if("tariff"===t){const t=this._hass?.states["sensor.sem_tariff_current_import_rate"],i=this._hass?.states["sensor.sem_tariff_current_export_rate"],s=this._hass?.states[`${this._prefix}tariff_price_level`],r=t?.state??"—",a=t?.attributes?.unit_of_measurement||e,o=i?.state??"—",n=i?.attributes?.unit_of_measurement||e,l=s?.state??"—",c=this._entityExists("number.sem_electricity_import_rate"),d=this._entityExists("number.sem_electricity_export_rate");return H`
                <div class="info-tiles tariff-info-tiles">
                    ${this._renderInfoTile("mdi:transmission-tower-import","#488fc2","current_import_rate",`${r} ${a}`)}
                    ${this._renderInfoTile("mdi:transmission-tower-export","#8353d1","current_export_rate",`${o} ${n}`)}
                    ${this._renderInfoTile("mdi:signal-cellular-outline","#96CAEE","price_level",l)}
                </div>
                ${c?this._renderStepper("number.sem_electricity_import_rate","current_import_rate"):K}
                ${d?this._renderStepper("number.sem_electricity_export_rate","current_export_rate"):K}
            `}return K}_renderSection(t,e){const i=this._collapsed[t.id],s=this._sectionSubtitle(t.id,e);return H`
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
                ${i?K:H`
                    <div class="section-body">
                        ${this._renderSectionBody(t.id,e)}
                    </div>
                `}
            </div>
        `}render(){if(!this._config||!this._hass)return K;const t=_t(this._hass);return H`
            <div class="wrap">
                ${Xt.map(e=>this._renderSection(e,t))}
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
        `}getCardSize(){return 8}static getStubConfig(){return{entity_prefix:"sensor.sem_"}}},{type:"custom:sem-costs-detail-card",name:"SEM Costs Detail Card",description:"Financial details — EV economics, investment, demand charge, and tariff rates",preview:!1});const Zt="sensor.sem_";ft("sem-charger-status-card",class extends mt{constructor(){super(),this._chargers=[],this._lastStateCount=0}set hass(t){this._hass,this._hass=t;const e=t?.language,i="function"==typeof semLocalize;let s=!1;if((e!==this._lang||i&&!this._localizeReady)&&(this._lang=e,this._localizeReady=i,s=!0),this._isFrozen()&&!s)return;if(this._chargers?.length>0&&!s){const e=this._config?.entity_prefix||Zt,i=t.states[`${e}charger_${this._chargers[0]}_power`]?.state;if("unavailable"===i||"unknown"===i)return}const r=Object.keys(t.states).length;if(r!==this._lastStateCount){this._lastStateCount=r;const e=[];for(const i of Object.keys(t.states)){const t=i.match(/^sensor\.sem_charger_(.+)_power$/);t&&e.push(t[1])}this._chargers=e}const a=this._config?.entity_prefix||Zt,o=this._chargers.map(e=>[`charger_${e}_power`,`charger_${e}_session_energy`,`charger_${e}_session_solar_share`,`charger_${e}_taper_trend`].map(e=>t.states[`${a}${e}`]?.state||"").join(":")).join("|");(o!==this._lastKey||s)&&(this._lastKey=o,this._scheduleUpdate())}get hass(){return this._hass}setConfig(t){super.setConfig(t),this._prefix=t.entity_prefix||Zt}_val(t,e=0){const i=this._hass?.states[`${this._prefix}${t}`];return i&&"unavailable"!==i.state&&"unknown"!==i.state&&parseFloat(i.state)||e}_valStr(t){const e=this._hass?.states[`${this._prefix}${t}`];return e&&"unavailable"!==e.state&&"unknown"!==e.state?e.state:""}_chargerName(t){const e=this._hass?.states[`${this._prefix}charger_${t}_power`];let i=t.replace(/_/g," ").replace(/\b\w/g,t=>t.toUpperCase());return e?.attributes?.friendly_name&&(i=e.attributes.friendly_name.replace(/^SEM\s+/i,"").replace(/\s+Power$/i,"")),i}_renderChargerTile(t){const e=this._val(`charger_${t}_power`),i=this._val(`charger_${t}_session_energy`),s=this._val(`charger_${t}_session_solar_share`),r=this._valStr(`charger_${t}_taper_trend`)||"stable",a=this._t(r),o=this._chargerName(t),n=e>50,l=n?"#8DC892":"#888",c=n?this._t("charging"):this._t("idle");return H`
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
        `}render(){return this._config&&this._hass?H`
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
        `}getCardSize(){return Math.max(2,this._chargers.length)}static getStubConfig(){return{}}},{type:"sem-charger-status-card",name:"SEM Charger Status",description:"Multi-charger status display with per-charger tiles"});const Jt="sensor.sem_",Qt=["#8DC892","#64B5F6"];ft("sem-ev-status-card",class extends mt{constructor(){super(),this._chargers=[],this._lastStateCount=0}set hass(t){this._hass,this._hass=t;const e=t?.language,i="function"==typeof semLocalize;let s=!1;if((e!==this._lang||i&&!this._localizeReady)&&(this._lang=e,this._localizeReady=i,s=!0),this._isFrozen()&&!s)return;const r=Object.keys(t.states).length;if(r!==this._lastStateCount){this._lastStateCount=r;const e=[];for(const i of Object.keys(t.states)){const t=i.match(/^sensor\.sem_charger_(.+)_power$/);t&&e.push(t[1])}this._chargers=e}const a=this._config?.entity_prefix||Jt;let o=["ev_connected","ev_charging","ev_power","calculated_current","session_energy","session_solar_share","session_cost","daily_ev_energy","charging_state"].map(e=>{const i="ev_connected"===e||"ev_charging"===e?"binary_sensor.sem_":a;return t.states[`${i}${e}`]?.state||""}).join(",");this._chargers.length>=1&&(o+="|"+this._chargers.map(e=>[`charger_${e}_power`,`charger_${e}_session_energy`,`charger_${e}_daily_energy`,`charger_${e}_session_solar_share`,`charger_${e}_estimated_soc`,`charger_${e}_nights_until_charge`,`charger_${e}_charge_needed`].map(e=>t.states[`${a}${e}`]?.state||"").join(":")).join("|"),o+="|"+this._chargers.map(e=>t.states[`switch.sem_charger_${e}_night_charging`]?.state||"").join(":"),o+="|"+this._chargers.map(e=>t.states[`number.sem_charger_${e}_daily_ev_target`]?.state||"").join(":")),o+="|"+this._localizeReady+"|"+this._lang,(o!==this._lastKey||s)&&(this._lastKey=o,this._scheduleUpdate())}get hass(){return this._hass}setConfig(t){super.setConfig(t),this._prefix=t.entity_prefix||Jt}_binaryState(t){const e=this._hass?.states[`binary_sensor.sem_${t}`];return"on"===e?.state}_val(t,e=0){const i=this._hass?.states[`${this._prefix}${t}`];return i&&"unavailable"!==i.state&&"unknown"!==i.state&&parseFloat(i.state)||e}_valStr(t){const e=this._hass?.states[`${this._prefix}${t}`];return e?.state||""}_entityVal(t,e=0){const i=this._frozenEntities[t];if(i)return i.value;const s=this._hass?.states[t];return s&&"unavailable"!==s.state&&"unknown"!==s.state?parseFloat(s.state)??e:e}_fmt(t,e=1){return null==t||isNaN(t)?"—":t.toFixed(e)}_chargerName(t){const e=this._hass?.states[`${this._prefix}charger_${t}_power`];let i=t.replace(/_/g," ").replace(/\b\w/g,t=>t.toUpperCase());return e?.attributes?.friendly_name&&(i=e.attributes.friendly_name.replace(/^SEM\s+/i,"").replace(/\s+Power$/i,"")),i}_renderSocGauge(t){const e=null!=t?Math.max(0,Math.min(100,t)):0,i=e>60?"#8DC892":e>30?"#ff9800":"#f06292",s=Math.max(2,e/100*52);return H`
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
        `}_renderChargerSection(t,e){const i=Qt[e%Qt.length],s=this._val(`charger_${t}_power`,0),r=this._val(`charger_${t}_session_energy`,0),a=this._val(`charger_${t}_daily_energy`,0),o=this._val(`charger_${t}_session_solar_share`,0),n=this._val(`charger_${t}_estimated_soc`,null),l=this._entityVal(`number.sem_charger_${t}_nights_until_charge`,null),c=this._valStr(`charger_${t}_charge_needed`),d=this._chargerName(t),h=s>50,p=h?this._t("charging"):this._t("idle"),g=this._hass?.states[`switch.sem_charger_${t}_night_charging`],_="on"===g?.state,u=this._entityVal(`number.sem_charger_${t}_daily_ev_target`,10),f=this._entityVal(`number.sem_charger_${t}_night_initial_current`,10),m=this._entityVal(`number.sem_charger_${t}_minimum_current`,6),v="True"===c||"true"===c,y=v?"mdi:battery-alert":"mdi:battery-check",x=v?"#f06292":"#8DC892",b=v?this._t("yes"):this._t("no"),$=`switch.sem_charger_${t}_night_charging`;return H`
            <div class="charger-section">
                <div class="charger-header">
                    <div class="charger-dot" style="background:${i}"></div>
                    <span class="charger-name">${d}</span>
                    <span class="charger-status" style="color:${h?i:""}">${p}</span>
                </div>

                <div class="charger-body">
                    <div class="charger-soc">
                        ${this._renderSocGauge(n)}
                        <span class="soc-label">SOC</span>
                    </div>

                    <div class="charger-metrics">
                        <div class="cm-row">
                            <span class="cm-label">${this._t("power")}</span>
                            <span class="cm-value" style="color:${h?i:""}">${pt(s)}</span>
                        </div>
                        <div class="cm-row">
                            <span class="cm-label">${this._t("today")}</span>
                            <span class="cm-value">${this._fmt(a,1)} kWh</span>
                        </div>
                        <div class="cm-row">
                            <span class="cm-label">${this._t("session")}</span>
                            <span class="cm-value">${this._fmt(r,1)} kWh</span>
                        </div>
                        <div class="cm-row">
                            <span class="cm-label">${this._t("solar_share")}</span>
                            <span class="cm-value" style="color:#ff9800">${this._fmt(o,0)}%</span>
                        </div>
                        <div class="cm-row">
                            <span class="cm-label">${this._t("charge_tonight")}</span>
                            <span class="cm-value" style="color:${x}">
                                <ha-icon icon="${y}" style="--mdc-icon-size:14px;vertical-align:middle;color:${x}"></ha-icon>
                                ${b}
                            </span>
                        </div>
                        ${null!=l?H`
                            <div class="cm-row">
                                <span class="cm-label">${this._t("nights_until_charge")}</span>
                                <span class="cm-value">${Math.round(l)}</span>
                            </div>
                        `:K}
                    </div>
                </div>

                <div class="charger-settings">
                    <div class="setting-item">
                        <ha-icon icon="mdi:weather-night" style="--mdc-icon-size:16px;color:${_?"#7986CB":"#666"}"></ha-icon>
                        <span class="setting-label">${this._t("night")}</span>
                        <span
                            class="setting-toggle ${_?"on":"off"}"
                            @click=${t=>{t.stopPropagation(),this._toggleSwitch($)}}
                        >${_?"ON":"OFF"}</span>
                    </div>
                    <div
                        class="setting-item clickable"
                        @click=${()=>{const e=new CustomEvent("hass-more-info",{bubbles:!0,composed:!0,detail:{entityId:`number.sem_charger_${t}_daily_ev_target`}});this.dispatchEvent(e)}}
                    >
                        <ha-icon icon="mdi:bullseye-arrow" style="--mdc-icon-size:16px;color:#8DC892"></ha-icon>
                        <span class="setting-label">${this._t("night_target")}</span>
                        <span class="setting-value">${this._fmt(u,1)} kWh</span>
                    </div>
                    <div
                        class="setting-item clickable"
                        @click=${()=>{const e=new CustomEvent("hass-more-info",{bubbles:!0,composed:!0,detail:{entityId:`number.sem_charger_${t}_night_initial_current`}});this.dispatchEvent(e)}}
                    >
                        <ha-icon icon="mdi:current-ac" style="--mdc-icon-size:16px;color:#64B5F6"></ha-icon>
                        <span class="setting-value">${this._fmt(f,0)}A</span>
                    </div>
                    <div
                        class="setting-item clickable"
                        @click=${()=>{const e=new CustomEvent("hass-more-info",{bubbles:!0,composed:!0,detail:{entityId:`number.sem_charger_${t}_minimum_current`}});this.dispatchEvent(e)}}
                    >
                        <ha-icon icon="mdi:speedometer-slow" style="--mdc-icon-size:16px;color:#ff9800"></ha-icon>
                        <span class="setting-value">${this._fmt(m,0)}A</span>
                    </div>
                </div>
            </div>
        `}render(){if(!this._config||!this._hass)return K;const t=this._binaryState("ev_connected"),e=this._binaryState("ev_charging"),i=this._val("ev_power",0),s=this._val("calculated_current",0),r=this._val("session_energy",0),a=this._val("session_solar_share",0),o=this._val("session_cost",0),n=this._val("daily_ev_energy",0),l=this._valStr("charging_state"),c=_t(this._hass),d=this._hass?.states["select.sem_ev_charging_mode"],h=d?.state||"auto",p={auto:this._t("mode_auto"),minpv:this._t("mode_minpv"),now:this._t("maximum"),off:this._t("off")},g=e?"wrap state-charging":t?"wrap state-connected":"wrap state-disconnected",_=e?this._t("charging"):t?this._t("connected"):this._t("disconnected"),u=e?"status-value charging":t?"status-value connected":"status-value disconnected";return H`
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
                <div class="${g}">
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

                        <div class="metrics-col">
                            <div class="metric-row">
                                <span class="metric-label">${this._t("status")}</span>
                                <span class="${u}">${_}</span>
                            </div>
                            ${e?H`
                                <div class="metric-row power-row">
                                    <span class="metric-label">${this._t("power")}</span>
                                    <span class="metric-value power-value">${pt(i)}</span>
                                </div>
                            `:K}
                            <div class="metric-row">
                                <span class="metric-label">${this._t("current")}</span>
                                <span class="metric-value">${this._fmt(s,0)} A</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("session")}</span>
                                <span class="metric-value">${this._fmt(r,1)} kWh</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("today")}</span>
                                <span class="metric-value">${this._fmt(n,1)} kWh</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("solar_share")}</span>
                                <span class="metric-value solar-share-value">${this._fmt(a,0)}%</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("strategy")}</span>
                                <span class="strategy-value">${l||"—"}</span>
                            </div>
                            <div class="metric-row">
                                <span class="metric-label">${this._t("mode")}</span>
                                <span class="metric-value">${p[h]||h}</span>
                            </div>
                        </div>
                    </div>

                    <div class="bottom-bar">
                        <div class="chip">
                            <span class="chip-label">${this._t("session_cost")}</span>
                            <span class="cost-chip-value">${this._fmt(o,2)} ${c}</span>
                        </div>
                    </div>

                    ${this._chargers.length>=1?H`
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

            @media (max-width: 400px) {
                .hero { flex-direction: column; align-items: center; text-align: center; }
                .ev-icon-area { width: 80px; height: 80px; }
                .metric-row { justify-content: center; gap: 8px; }
                .metrics-col { align-items: center; }
            }
        `}getCardSize(){return this._chargers.length>=1?3+2*this._chargers.length:3}static getStubConfig(){return{}}},{type:"sem-ev-status-card",name:"SEM EV Status",description:"Lumina-styled EV charging hero card with per-charger intelligence and settings"});const te=["sensor.sem_solar_power","sensor.sem_battery_soc","sensor.sem_autarky_rate","sensor.sem_ev_power","sensor.sem_energy_optimization_score","sensor.sem_energy_tip","sensor.sem_best_surplus_window","sensor.sem_forecast_remaining_today_kwh","sensor.sem_current_vs_peak_percentage","sensor.sem_consecutive_peak_15min","sensor.sem_target_peak_limit","sensor.sem_daily_co2_avoided","sensor.sem_lifetime_co2_avoided","sensor.sem_diag_forecast_provider","switch.sem_observer_mode"];ft("sem-home-status-card",class extends mt{static get watchedEntities(){return te}setConfig(t){super.setConfig(t),this._prefix=t.entity_prefix||"sensor.sem_"}_val(t,e=0){const i=this._hass?.states[`${this._prefix}${t}`];return i&&"unavailable"!==i.state&&"unknown"!==i.state&&parseFloat(i.state)||e}_valStr(t){const e=this._hass?.states[`${this._prefix}${t}`];return e&&"unavailable"!==e.state&&"unknown"!==e.state?e.state:""}_switchOn(t){const e=this._frozenEntities[t];return e?"on"===e.value:"on"===this._hass?.states[t]?.state}_scoreColor(t){return t>=80?"#8DC892":t>=50?"#ff9800":"#f44336"}_peakColor(t){return t>90?"#f44336":t>70?"#ff9800":"#8DC892"}_peakStatusKey(t){return t>90?"peak_critical":t>70?"peak_warning":"peak_safe"}_renderChip(t,e,i){return H`
            <div class="chip">
                <ha-icon icon="${t}" style="--mdc-icon-size:16px;color:${e}"></ha-icon>
                <span class="chip-val">${i}</span>
            </div>
        `}render(){if(!this._config||!this._hass)return K;const t=this._val("solar_power"),e=this._val("battery_soc"),i=this._val("autarky_rate"),s=this._val("ev_power"),r=this._val("energy_optimization_score"),a=this._scoreColor(r),o=this._valStr("energy_tip"),n=this._valStr("best_surplus_window")||"—",l=this._val("forecast_remaining_today_kwh").toFixed(1),c=this._val("current_vs_peak_percentage"),d=this._peakColor(c),h=this._val("consecutive_peak_15min").toFixed(1),p=this._val("target_peak_limit").toFixed(1);this._switchOn("switch.sem_observer_mode");const g=this._valStr("diag_forecast_provider")||"—",_=this._val("daily_co2_avoided").toFixed(2),u=this._val("lifetime_co2_avoided").toFixed(1);return H`
            <div class="wrap">

                <!-- 1. Status Chips -->
                <div class="chips-row">
                    ${this._renderChip("mdi:solar-power","#ff9800",pt(t))}
                    ${this._renderChip("mdi:battery","#4db6ac",`${e.toFixed(0)}%`)}
                    ${this._renderChip("mdi:leaf","#8DC892",`${i.toFixed(0)}%`)}
                    ${this._renderChip("mdi:car-electric","#8DC892",s>0?pt(s):"—")}
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
                        <span class="peak-detail">${h} / ${p} kW (${c.toFixed(0)}%)</span>
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
                        <span class="forecast-val">${g}</span>
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
                            <span class="env-chip-val">${u} kg</span>
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
        `}getCardSize(){return 5}static getStubConfig(){return{entity_prefix:"sensor.sem_"}}},{type:"custom:sem-home-status-card",name:"SEM Home Status Card",description:"Consolidated status panel for the SEM Home tab",preview:!1});const ee=[{id:"info",icon:"mdi:information-outline",color:"#96CAEE",titleKey:"system_info",subtitleFn:t=>`v${t._val("diag_version")||"—"} · ${t._val("diag_grid_mode")||"—"}`},{id:"health",icon:"mdi:heart-pulse",color:"#8DC892",titleKey:"health_overview",subtitleFn:t=>`${t._valNum("solar_power").toFixed(0)}W solar · SOC ${t._valNum("battery_soc").toFixed(0)}%`},{id:"modes",icon:"mdi:toggle-switch-outline",color:"#96CAEE",titleKey:"mode_controls",subtitleFn:t=>[t._switchOn("observer_mode")&&"Observer",t._switchOn("night_charging")&&"Night"].filter(Boolean).join(" · ")||"—"},{id:"diag",icon:"mdi:bug-outline",color:"#ff9800",titleKey:"diagnostics",subtitleFn:()=>""}],ie=[{key:"solar_power",icon:"mdi:solar-power",color:"#ff9800",suffix:"W"},{key:"grid_power",icon:"mdi:transmission-tower",color:"#488fc2",suffix:"W"},{key:"battery_soc",icon:"mdi:battery",color:"#4db6ac",suffix:"%"},{key:"ev_power",icon:"mdi:ev-station",color:"#8DC892",suffix:"W"},{key:"forecast_today",icon:"mdi:weather-sunny",color:"#ff9800",suffix:"kWh"},{key:"tariff_current_import_rate",icon:"mdi:tag",color:"#96CAEE",suffix:""}],se=["sensor.sem_diag_version","sensor.sem_diag_grid_mode","sensor.sem_diag_battery_capacity","sensor.sem_diag_update_interval","sensor.sem_diag_charger_count","sensor.sem_diag_charger_control_type","sensor.sem_diag_unavailable_sensors","sensor.sem_solar_power","sensor.sem_grid_power","sensor.sem_battery_soc","sensor.sem_ev_power","sensor.sem_forecast_today","sensor.sem_tariff_current_import_rate","switch.sem_observer_mode","switch.sem_night_charging","switch.sem_smart_night_charging","sensor.sem_home_consumption_power","sensor.sem_grid_import_power","sensor.sem_grid_export_power","sensor.sem_autarky_rate","sensor.sem_self_consumption_rate","sensor.sem_battery_power","sensor.sem_night_mode","sensor.sem_solar_mode","sensor.sem_ev_connected","sensor.sem_calculated_current","sensor.sem_daily_ev_energy","sensor.sem_daily_ev_target","sensor.sem_night_mode_status","sensor.sem_solar_mode_status","sensor.sem_battery_status","sensor.sem_grid_status"];ft("sem-system-card",class extends mt{static get watchedEntities(){return se}constructor(){super(),this._collapsed={info:!1,health:!1,modes:!0,diag:!0},this._copyFeedback=""}setConfig(t){super.setConfig(t),this._prefix=t.entity_prefix||"sensor.sem_"}_val(t){const e=this._hass?.states[`${this._prefix}${t}`];return e&&"unavailable"!==e.state&&"unknown"!==e.state?e.state:""}_valNum(t,e=0){const i=this._hass?.states[`${this._prefix}${t}`];return i&&"unavailable"!==i.state&&"unknown"!==i.state&&parseFloat(i.state)||e}_switchOn(t){return"on"===this._hass?.states[`switch.sem_${t}`]?.state}_available(t){const e=this._hass?.states[t];return!(!e||"unavailable"===e.state||"unknown"===e.state)}_toggleSection(t){this._collapsed={...this._collapsed,[t]:!this._collapsed[t]},this.requestUpdate()}_copyDiagnostics(){const t=this._val("diag_version")||"—",e=this._val("diag_grid_mode")||"—",i=this._val("diag_charger_count")||"—",s=this._val("diag_charger_control_type")||"—",r=this._valNum("diag_battery_capacity"),a=`SEM ${t} | Grid: ${e} | Chargers: ${i} (${s}) | Battery: ${r>0?r.toFixed(1):"—"}kWh | Unavailable: ${this._val("diag_unavailable_sensors")||"0"}`;navigator.clipboard.writeText(a).then(()=>{this._copyFeedback=this._t("copied"),this.requestUpdate(),setTimeout(()=>{this._copyFeedback="",this.requestUpdate()},2e3)}).catch(t=>{console.error("[SEM System] clipboard copy failed",t)})}_renderSectionHeader(t,e){const i=this._collapsed[t.id],s=i?"rotate(-90deg)":"rotate(0deg)";return H`
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
        `}_renderInfoSection(t){const e=this._valNum("diag_battery_capacity"),i=this._valNum("diag_update_interval"),s=this._val("diag_charger_count")||"—",r=this._val("diag_charger_control_type")||"",a=r?`${s} (${r})`:s;return H`
            <div class="info-row">
                <span class="info-row-label">${this._t("version")}</span>
                <span class="info-row-value">${this._val("diag_version")||"—"}</span>
            </div>
            <div class="info-row">
                <span class="info-row-label">${this._t("grid_mode")}</span>
                <span class="info-row-value">${this._val("diag_grid_mode")||"—"}</span>
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
                <span class="info-row-value">${this._val("diag_unavailable_sensors")||"0"}</span>
            </div>
        `}_renderHealthSection(t){return H`
            <div class="health-chips">
                ${ie.map(t=>{const e=`${this._prefix}${t.key}`,i=this._available(e),s=this._hass?.states[e],r=s?s.state:"—";return H`
                        <div class="health-chip" style="background:${i?"rgba(141,200,146,0.12)":"rgba(244,67,54,0.12)"};border:1px solid ${i?"rgba(141,200,146,0.3)":"rgba(244,67,54,0.3)"}">
                            <ha-icon icon="${t.icon}" style="--mdc-icon-size:16px;color:${t.color}"></ha-icon>
                            <span class="chip-value">${i?`${r}${t.suffix}`:"—"}</span>
                        </div>
                    `})}
            </div>
        `}_renderToggle(t,e,i){const s="on"===this._hass?.states[t]?.state;return H`
            <div class="toggle-row">
                <span class="toggle-label">${this._t(e)}</span>
                <div
                    class="toggle-track ${s?"on":""}"
                    @click=${()=>this._toggleSwitch(t)}
                >
                    <div class="toggle-thumb"></div>
                </div>
            </div>
        `}_renderModesSection(t){return H`
            <div class="toggle-group">
                ${this._renderToggle("switch.sem_night_charging","night_charging",t)}
                ${this._renderToggle("switch.sem_smart_night_charging","smart_night",t)}
            </div>
        `}_renderDiagBlock(t,e){return H`
            <div class="diag-block">
                <span class="diag-block-label">${this._t(t)}</span>
                <span class="diag-block-text">${e}</span>
            </div>
        `}_renderDiagSection(t){const e=`Solar ${this._valNum("solar_power").toFixed(0)}W · Grid ${this._valNum("grid_power").toFixed(0)}W · Battery ${this._valNum("battery_power").toFixed(0)}W · SOC ${this._valNum("battery_soc").toFixed(0)}% · EV ${this._valNum("ev_power").toFixed(0)}W`,i=`Home ${this._valNum("home_consumption_power").toFixed(0)}W · Import ${this._valNum("grid_import_power").toFixed(0)}W · Export ${this._valNum("grid_export_power").toFixed(0)}W · Autarky ${this._valNum("autarky_rate").toFixed(0)}% · Self ${this._valNum("self_consumption_rate").toFixed(0)}%`,s=`Night mode: ${this._val("night_mode")||"—"} · Solar: ${this._val("solar_mode")||"—"} · ${this._val("calculated_current")||"—"}A · ${this._valNum("daily_ev_energy").toFixed(1)}/${this._val("daily_ev_target")||"—"}kWh · Plug: ${this._val("ev_connected")||"—"}`,r=`Night: ${this._val("night_mode_status")||"—"} · Solar: ${this._val("solar_mode_status")||"—"} · Battery: ${this._val("battery_status")||"—"} · Grid: ${this._val("grid_status")||"—"}`;return H`
            ${this._renderDiagBlock("source_sensors",e)}
            ${this._renderDiagBlock("derived_values",i)}
            ${this._renderDiagBlock("ev_charging",s)}
            ${this._renderDiagBlock("mode_status",r)}
        `}_renderSection(t,e,i){const s=this._collapsed[t.id];return H`
            <div class="section">
                ${this._renderSectionHeader(t,i)}
                <div class="section-content ${s?"":"expanded"}">
                    <div class="section-body">
                        ${e(i)}
                    </div>
                </div>
            </div>
        `}render(){if(!this._config)return K;const t=this._theme(),e=!1!==t.isDark,i=t.accent||"#42a5f5",s={info:t=>this._renderInfoSection(t),health:t=>this._renderHealthSection(t),modes:t=>this._renderModesSection(t),diag:t=>this._renderDiagSection(t)};return H`
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
                ${ee.map(e=>this._renderSection(e,s[e.id],t))}
                <div class="copy-row">
                    <button class="copy-btn" @click=${()=>this._copyDiagnostics()}>
                        <ha-icon icon="mdi:content-copy" style="--mdc-icon-size:16px"></ha-icon>
                        ${this._t("copy_diagnostics")}
                    </button>
                    <span class="copy-feedback">${this._copyFeedback}</span>
                </div>
            </div>
        `}getCardSize(){return 8}static getStubConfig(){return{entity_prefix:"sensor.sem_"}}},{type:"custom:sem-system-card",name:"SEM System Card",description:"Consolidated system panel for Solar Energy Management",preview:!1});const re=2;class ae{constructor(t){}get _$AU(){return this._$AM._$AU}_$AT(t,e,i){this._$Ct=t,this._$AM=e,this._$Ci=i}_$AS(t,e){return this.update(t,e)}update(t,e){return this.render(...e)}}class oe extends ae{constructor(t){if(super(t),this.it=K,t.type!==re)throw Error(this.constructor.directiveName+"() can only be used in child bindings")}render(t){if(t===K||null==t)return this._t=void 0,this.it=t;if(t===G)return t;if("string"!=typeof t)throw Error(this.constructor.directiveName+"() called with a non-string value");if(t===this.it)return this._t;this.it=t;const e=[t];return e.raw=e,this._t={_$litType$:this.constructor.resultType,strings:e,values:[]}}}oe.directiveName="unsafeHTML",oe.resultType=1;class ne extends oe{}ne.directiveName="unsafeSVG",ne.resultType=2;const le=(t=>(...e)=>({_$litDirective$:t,values:e}))(ne),ce={solar:{nameKey:"solar",color:"#ff9800"},grid:{nameKey:"grid",color_import:"#488fc2",color_export:"#8353d1"},battery:{nameKey:"battery",color:"#4db6ac"},home:{nameKey:"home",color:"#5BC8D8"},ev:{nameKey:"ev_charger",color:"#8DC892"},inverter:{nameKey:"inverter",color:"#96CAEE"}};ft("sem-flow-card",class extends mt{constructor(){super(),this._lastKey="",this._animFrames={},this._currentValues={},this._compact=!1,this._visible=!0,this._deviceConfigSig="",this._devicePositions=[],this._updateTimer=null,this._resizeObserver=null,this._intersectionObserver=null,this._resizeTimeout=null,this._mode="prefix",this._prefix="sensor.sem_",this._entities=null}setConfig(t){if(this._config=t,t.entity_prefix)this._mode="prefix",this._prefix=t.entity_prefix;else{if(!t.entities)throw new Error('sem-flow-card requires either "entities" or "entity_prefix" config');this._mode="entities",this._entities=t.entities}this._showLabels=!1!==t.show_labels,this._showValues=!1!==t.show_values,this._showGlow=!1!==t.show_glow,this._showInverter=!1!==t.show_inverter,this.requestUpdate()}set hass(t){this._hass,this._hass=t;const e=t?.language;if(e!==this._lang)return this._lang=e,void this.requestUpdate();this._visible&&(clearTimeout(this._updateTimer),this._updateTimer=setTimeout(()=>this._updateFlowsImperative(),100))}get hass(){return this._hass}firstUpdated(){this._resizeTimeout=null,this._resizeObserver=new ResizeObserver(t=>{this._resizeTimeout&&clearTimeout(this._resizeTimeout),this._resizeTimeout=setTimeout(()=>{for(const e of t){const t=e.contentRect.width<400;t!==this._compact&&(this._compact=t,this._lastKey="",this._deviceConfigSig="",this.requestUpdate())}},100)}),this._resizeObserver.observe(this),this._intersectionObserver=new IntersectionObserver(t=>{this._visible=t[0].isIntersecting;const e=this.renderRoot.querySelector("svg");e&&(e.style.animationPlayState=this._visible?"running":"paused")},{threshold:.01}),this._intersectionObserver.observe(this)}disconnectedCallback(){super.disconnectedCallback(),this._resizeObserver&&(this._resizeObserver.disconnect(),this._resizeObserver=null),this._intersectionObserver&&(this._intersectionObserver.disconnect(),this._intersectionObserver=null),clearTimeout(this._updateTimer),clearTimeout(this._resizeTimeout);for(const t of Object.keys(this._animFrames))cancelAnimationFrame(this._animFrames[t]);this._animFrames={}}updated(){this._setupClickHandlers(),this._updateFlowsImperative()}static get styles(){return a`
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
        `}render(){if(!this._config)return K;const t=this._getLayout(),e=t.solar,i=t.inverter,s=t.battery,r=t.grid,a=t.home,o=t.ev,n=(2*Math.PI*t.socR).toFixed(1),l=(2*Math.PI*t.autarkyR).toFixed(1),c=t.font.label,d=t.font.value,h=t.font.sub,p=t.font.homeVal,g="'Segoe UI','Roboto',sans-serif",_=this._getNodeColor("grid_import"),u=this._getNodeColor("grid_export"),f=this._getNodeColor("solar"),m=this._getNodeColor("battery"),v=this._getNodeColor("home"),y=this._getNodeColor("ev"),x=ce.inverter.color,b=this._hasNode("solar"),$=this._hasNode("battery"),w=this._hasNode("grid"),k=this._hasNode("ev"),S=this._showInverter&&this._hasNode("inverter");return H`
            <ha-card>
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
                        ${this._svgRaw(this._glowFilter("glowGridImport",_,8))}
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
                    ${this._svgRaw(w?`<path id="track-grid" d="${t.paths.grid}" fill="none" stroke="${_}" stroke-width="1.5" stroke-dasharray="4,6" opacity="0.18"/>`:"")}
                    ${this._svgRaw(k?this._track(t.paths.ev,y):"")}

                    ${this._svgRaw(b?`<g id="flow-solar" class="flow-group" style="opacity:0" data-path-id="path-solar" data-path-d="${t.paths.solar}" data-color="${f}" data-count="2"></g>`:"")}
                    ${this._svgRaw($?`<g id="flow-battery" class="flow-group" style="opacity:0" data-path-id="path-battery" data-path-d="${t.paths.battery}" data-color="${m}" data-count="3"></g>`:"")}
                    ${this._svgRaw(w?`<g id="flow-grid" class="flow-group" style="opacity:0" data-path-id="path-grid" data-path-d="${t.paths.grid}" data-color="${_}" data-count="3"></g>`:"")}
                    ${this._svgRaw(b||S?`<g id="flow-home" class="flow-group" style="opacity:0" data-path-id="path-home" data-path-d="${t.paths.home}" data-color="${v}" data-count="2"></g>`:"")}
                    ${this._svgRaw(k?`<g id="flow-ev" class="flow-group" style="opacity:0" data-path-id="path-ev" data-path-d="${t.paths.ev}" data-color="${y}" data-count="3"></g>`:"")}

                    ${this._svgRaw(b?`\n                    <g id="node-solar" filter="url(#glowSolar)">\n                        ${this._glowRing(e,f)}\n                        <circle cx="${e.cx}" cy="${e.cy}" r="${e.r}" fill="${this._hexToRgba(f,.07)}" stroke="${f}" stroke-width="1.8"/>\n                        <g transform="translate(${e.cx},${e.cy-8})" stroke="${f}" fill="none" opacity="0.75">\n                            <rect x="-16" y="-12" width="32" height="24" rx="3" stroke-width="1.8"/>\n                            <line x1="-16" y1="0" x2="16" y2="0" stroke-width="1.2"/>\n                            <line x1="-5" y1="-12" x2="-5" y2="12" stroke-width="1.2"/>\n                            <line x1="5" y1="-12" x2="5" y2="12" stroke-width="1.2"/>\n                            <line x1="0" y1="12" x2="0" y2="17" stroke-width="1.5"/>\n                            <line x1="-7" y1="17" x2="7" y2="17" stroke-width="1.5"/>\n                        </g>\n                    </g>\n                    <text x="${e.cx}" y="${e.cy+e.r+18}" text-anchor="middle" font-family="${g}" font-size="${c}" font-weight="600" fill="${f}">${this._escSvg(this._getNodeName("solar"))}</text>\n                    <text id="val-solar" x="${e.cx}" y="${e.cy+e.r+18+.9*d}" text-anchor="middle" font-family="${g}" font-size="${d}" font-weight="700" fill="${f}">0 W</text>\n                    <text id="val-today-solar" x="${e.cx}" y="${e.cy+e.r+18+.9*d+h+4}" text-anchor="middle" font-family="${g}" font-size="${h}" fill="${f}" opacity="0.7"> </text>\n                    `:"")}

                    ${this._svgRaw(S?`\n                    <g id="node-inverter" filter="url(#glowInverter)">\n                        <circle cx="${i.cx}" cy="${i.cy}" r="${i.r}" fill="${this._hexToRgba(x,.07)}" stroke="${x}" stroke-width="1"/>\n                        <path d="M${i.cx-10},${i.cy} Q${i.cx-4},${i.cy-8} ${i.cx},${i.cy} Q${i.cx+4},${i.cy+8} ${i.cx+10},${i.cy}" fill="none" stroke="${x}" stroke-width="1.8" opacity="0.7"/>\n                    </g>\n                    <text id="val-inverter-status" x="${i.cx}" y="${i.cy+i.r+14}" text-anchor="middle" font-family="${g}" font-size="${this._compact?11:10}" fill="var(--secondary-text-color,#5a7a9a)" opacity="0.7"> </text>\n                    `:"")}

                    ${this._svgRaw($?`\n                    <g id="node-battery" filter="url(#glowBattery)">\n                        ${this._glowRing(s,m)}\n                        <circle cx="${s.cx}" cy="${s.cy}" r="${s.r}" fill="${this._hexToRgba(m,.07)}" stroke="${m}" stroke-width="1.8"/>\n                        <circle cx="${s.cx}" cy="${s.cy}" r="${t.socR}" fill="none" stroke="${this._hexToRgba(m,.1)}" stroke-width="5"/>\n                        <circle id="soc-arc" cx="${s.cx}" cy="${s.cy}" r="${t.socR}" fill="none" stroke="${m}" stroke-width="5"\n                                stroke-dasharray="${n}" stroke-dashoffset="${n}"\n                                transform="rotate(-90 ${s.cx} ${s.cy})" stroke-linecap="round" opacity="0.75"/>\n                        <g transform="translate(${s.cx},${s.cy}) scale(0.8)" stroke="${m}" fill="none" opacity="0.7">\n                            <rect x="-8" y="-13" width="16" height="26" rx="3" stroke-width="1.8"/>\n                            <rect x="-3" y="-16" width="6" height="4" rx="1.5" fill="${m}" opacity="0.5" stroke="none"/>\n                        </g>\n                    </g>\n                    <text x="${s.cx}" y="${s.cy+s.r+18}" text-anchor="middle" font-family="${g}" font-size="${c}" font-weight="600" fill="${m}">${this._escSvg(this._getNodeName("battery"))}</text>\n                    <text id="val-battery-soc" x="${s.cx}" y="${s.cy+s.r+18+.9*d}" text-anchor="middle" font-family="${g}" font-size="${d}" font-weight="700" fill="${m}">0%</text>\n                    <text id="val-battery-power" x="${s.cx}" y="${s.cy+s.r+18+.9*d+c}" text-anchor="middle" font-family="${g}" font-size="${c}" font-weight="500" fill="${m}" opacity="0.7">0 W</text>\n                    <text id="label-battery-state" x="${s.cx}" y="${s.cy+s.r+18+.9*d+2*c}" text-anchor="middle" font-family="${g}" font-size="${h}" fill="${m}" opacity="0.7"></text>\n                    <text id="val-today-battery" x="${s.cx}" y="${s.cy+s.r+18+.9*d+2*c+h+4}" text-anchor="middle" font-family="${g}" font-size="${h}" fill="${m}" opacity="0.65"> </text>\n                    `:"")}

                    ${this._svgRaw(w?`\n                    <g id="node-grid" filter="url(#glowGridImport)">\n                        ${this._glowRing(r,_)}\n                        <circle id="grid-circle" cx="${r.cx}" cy="${r.cy}" r="${r.r}" fill="${this._hexToRgba(_,.07)}" stroke="${_}" stroke-width="1.8"/>\n                        <g id="grid-icon" transform="translate(${r.cx},${r.cy})" stroke="${_}" fill="none" opacity="0.7" stroke-width="1.8" stroke-linecap="round">\n                            <line x1="0" y1="-16" x2="0" y2="14"/>\n                            <line x1="-10" y1="-8" x2="10" y2="-8"/>\n                            <line x1="-7" y1="-1" x2="7" y2="-1"/>\n                            <line x1="-10" y1="-8" x2="-5" y2="14"/>\n                            <line x1="10" y1="-8" x2="5" y2="14"/>\n                        </g>\n                    </g>\n                    <text x="${r.cx}" y="${r.cy+r.r+18}" text-anchor="middle" font-family="${g}" font-size="${c}" font-weight="600" fill="${_}">${this._escSvg(this._getNodeName("grid"))}</text>\n                    <text id="val-grid" x="${r.cx}" y="${r.cy+r.r+18+.9*d}" text-anchor="middle" font-family="${g}" font-size="${d}" font-weight="700" fill="${_}">0 W</text>\n                    <text id="label-grid" x="${r.cx}" y="${r.cy+r.r+18+.9*d+c}" text-anchor="middle" font-family="${g}" font-size="${h}" font-weight="500" fill="${_}" opacity="0.7">GRID</text>\n                    <text id="val-today-grid" x="${r.cx}" y="${r.cy+r.r+18+.9*d+c+h+4}" text-anchor="middle" font-family="${g}" font-size="${h}" fill="${_}" opacity="0.65"> </text>\n                    `:"")}

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
                    <text x="${a.cx}" y="${a.cy+a.r+18}" text-anchor="middle" font-family="${g}" font-size="${c+1}" font-weight="600" fill="${v}">${this._escSvg(this._getNodeName("home"))}</text>
                    <text id="val-home" x="${a.cx}" y="${a.cy+a.r+18+.9*p}" text-anchor="middle" font-family="${g}" font-size="${p}" font-weight="700" fill="${v}">0 W</text>
                    <text id="val-autarky" x="${a.cx}" y="${a.cy+a.r+18+.9*p+h+4}" text-anchor="middle" font-family="${g}" font-size="${h}" fill="${v}" opacity="0.7">\u00A0</text>
                    <text id="val-today-home" x="${a.cx}" y="${a.cy+a.r+18+.9*p+2*(h+4)}" text-anchor="middle" font-family="${g}" font-size="${h}" fill="${v}" opacity="0.65">\u00A0</text>

                    ${this._svgRaw(k?`\n                    <g id="node-ev" filter="url(#glowEV)">\n                        ${this._glowRing(o,y)}\n                        <circle cx="${o.cx}" cy="${o.cy}" r="${o.r}" fill="${this._hexToRgba(y,.07)}" stroke="${y}" stroke-width="1.8"/>\n                        <g transform="translate(${o.cx},${o.cy})" stroke="${y}" fill="none" opacity="0.7" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">\n                            <rect x="-8" y="-13" width="16" height="22" rx="3"/>\n                            <rect x="-5" y="-9" width="10" height="8" rx="1.5"/>\n                            <path d="M-1,-1 L0,3 L1,-1"/>\n                            <line x1="0" y1="9" x2="0" y2="13"/>\n                            <circle cx="0" cy="15" r="1.5" fill="${y}" opacity="0.4" stroke="none"/>\n                        </g>\n                    </g>\n                    <text x="${o.cx}" y="${o.cy+o.r+18}" text-anchor="middle" font-family="${g}" font-size="${c}" font-weight="600" fill="${y}">${this._escSvg(this._getNodeName("ev"))}</text>\n                    <text id="val-ev" x="${o.cx}" y="${o.cy+o.r+18+.9*d}" text-anchor="middle" font-family="${g}" font-size="${d}" font-weight="700" fill="${y}">0 W</text>\n                    <text id="val-today-ev" x="${o.cx}" y="${o.cy+o.r+18+.9*d+h+4}" text-anchor="middle" font-family="${g}" font-size="${h}" fill="${y}" opacity="0.65"> </text>\n                    <text id="val-ev-subtitle" x="${o.cx}" y="${o.cy+o.r+18+.9*d+2*(h+4)}" text-anchor="middle" font-family="${g}" font-size="${h-1}" fill="${y}" opacity="0.6"></text>\n                    `:"")}

                    <g id="device-labels"></g>

                    <text x="${this._compact?470:960}" y="${this._compact?1050:770}" text-anchor="end"
                          font-family="${g}" font-size="10" font-weight="300" letter-spacing="2"
                          fill="var(--secondary-text-color,#808080)" opacity="0.15">SEM</text>
                </svg>
            </ha-card>
        `}_svgRaw(t){return t?le(t):K}_escSvg(t){return t?String(t).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;"):""}_updateFlowsImperative(){if(!this._hass)return;let t,e,i,s=this._getState("solar_power");if(this._entities?.solar?.reverse&&(s=-s),"entities"===this._mode&&(this._entities?.battery?.charge||this._entities?.battery?.discharge))t=this._getState("battery_charge_power")-this._getState("battery_discharge_power");else{let e=this._getState("battery_power");t=this._entities?.battery?.reverse?-e:e}if("entities"===this._mode&&this._entities?.grid?.entity){const t=this._getState("grid_power"),s=this._entities.grid.reverse;e=Math.max(0,s?-t:t),i=Math.max(0,s?t:-t)}else e=this._getState("grid_import_power"),i=this._getState("grid_export_power");let r=this._getState("ev_power");this._entities?.ev?.invert&&(r=-r);const a=this._getState("battery_soc"),o=this._getState("autarky_rate"),n=Math.max(0,t),l=Math.max(0,-t),c=this._getEntityId("home_consumption_power");let d;c&&this._hass?.states[c]?(d=this._getState("home_consumption_power"),this._entities?.home?.invert&&(d=-d)):d=Math.max(0,s+e+l-i-n-r);const h=this._getStateStr("daily_solar_energy"),p=this._getStateStr("daily_ev_energy"),g=this._getStateStr("daily_grid_import_energy"),_=this._getStateStr("daily_grid_export_energy"),u=this._getStateStr("daily_battery_energy"),f=this._getStateStr("daily_home_energy"),m={solar:s,battery:t,gridImport:e,gridExport:i,home:d,ev:r,soc:a,autarky:o,dailySolar:h,dailyEv:p,dailyGridImport:g,dailyGridExport:_,dailyBattery:u,dailyHome:f},v=JSON.stringify(m);if(this._lastKey===v)return;this._lastKey=v,this._animateValue("val-solar",s);const y=t>10?"▼ ":t<-10?"▲ ":"";this._animateValue("val-battery-power",Math.abs(t),800,t=>y+pt(t));const x=e>i,b=x?"↓ ":i>10?"↑ ":"";this._animateValue("val-grid",x?e:i,800,t=>b+pt(t)),this._animateValue("val-home",d),this._animateValue("val-ev",r);const $=this._getState("ev_charger_count");this._setText("val-ev-subtitle",$>1?`(${$} ${this._t("chargers")})`:""),this._animateValue("val-battery-soc",a,800,t=>`${t.toFixed(0)}%`);const w=this._getEntityId("autarky_rate");w&&this._animateValue("val-autarky",o,800,t=>`⚡ ${t.toFixed(0)}% self`),this._setText("val-inverter-status",this._getStateStr("charging_state"));const k=this._t("today");this._setText("val-today-solar",h?`${k} ${h} kWh`:""),this._setText("val-today-ev",p?`${k} ${p} kWh`:""),this._setText("val-today-battery",u?`${k} ${u} kWh`:""),this._setText("val-today-home",f?`${k} ${f} kWh`:"");const S=[];if(g&&S.push(`↓${g}`),_&&S.push(`↑${_}`),g&&_){const t=(parseFloat(g)-parseFloat(_)).toFixed(1);S.push(`Net ${t>0?"+":""}${t}`)}this._setText("val-today-grid",S.length?S.join(" ")+" kWh":"");const C=this._getLayout(),E=this.renderRoot.getElementById("soc-arc");if(E){const t=2*Math.PI*C.socR;E.style.strokeDashoffset=(t*(1-a/100)).toFixed(1),E.style.animation=n>10?"socPulse 2s ease-in-out infinite":l>10?"socDrain 2.5s ease-in-out infinite":"none"}const z=this.renderRoot.getElementById("autarky-arc");if(z&&w&&o>0){const t=2*Math.PI*C.autarkyR;z.style.strokeDashoffset=(t*(1-o/100)).toFixed(1),z.style.stroke=this._autarkyColor(o),z.style.opacity="0.75"}else z&&(z.style.opacity="0");const M=x?this._getNodeColor("grid_import"):i>10?this._getNodeColor("grid_export"):this._getNodeColor("grid_import");this._updateGridColor(M,x);const D=this.renderRoot.getElementById("label-grid");D&&(D.textContent=x?this._t("importing"):i>10?this._t("exporting"):this._t("grid"));const F=n>10?"#f06292":l>10?"#4db6ac":this._getNodeColor("battery"),T=this.renderRoot.getElementById("label-battery-state");T&&(T.textContent=n>10?this._t("charging"):l>10?this._t("discharging"):"");for(const t of["val-battery-soc","val-battery-power","label-battery-state","val-today-battery"]){const e=this.renderRoot.getElementById(t);e&&e.setAttribute("fill",F)}const A=this.renderRoot.getElementById("soc-arc");A&&(n>10||l>10)&&(A.style.stroke=F),this._updateFlow("flow-solar",s>10,!1,gt(s)),this._updateFlow("flow-battery",Math.abs(t)>10,t<0,gt(t),F),this._updateFlow("flow-grid",e>10||i>10,x,gt(e||i),M),this._updateFlow("flow-home",d>10,!1,gt(d)),this._updateFlow("flow-ev",r>10,!1,gt(r)),this._setGlowIntensity("node-solar",s,1e4),this._setGlowIntensity("node-battery",Math.abs(t),5e3),this._setGlowIntensity("node-grid",Math.max(e,i),1e4),this._setGlowIntensity("node-home",d,8e3),this._setGlowIntensity("node-ev",r,11e3),this._updateDeviceLabels()}_updateFlow(t,e,i,s,r){const a=this.renderRoot.getElementById(t);if(!a)return;if(a.style.opacity=e?"1":"0",!e)return void(a.dataset.sig="");const o=r||a.dataset.color;r&&(a.dataset.color=r);const n=a.dataset.pathId,l=a.dataset.pathD,c=parseInt(a.dataset.count,10)||2,d=`${i?"r":"f"}:${s.toFixed(1)}:${o}`;a.dataset.sig!==d&&(a.dataset.sig=d,a.innerHTML=this._flowEffects(l,n,o,c,s,i))}_flowEffects(t,e,i,s,r,a){const o=r.toFixed(1),n=a?' keyPoints="1;0" keyTimes="0;1"':"";let l=`<path d="${t}" fill="none" stroke="${i}" stroke-width="3"\n                     stroke-dasharray="12,20" opacity="0.5" stroke-linecap="round">\n                     <animate attributeName="stroke-dashoffset" from="0" to="${a?"32":"-32"}"\n                              dur="${o}s" repeatCount="indefinite"/>\n                   </path>`;for(let t=0;t<s;t++){const a=t/s*r;l+=`\n                <circle r="5" fill="${i}" opacity="0.12">\n                    <animateMotion dur="${o}s" repeatCount="indefinite" calcMode="paced"${n} begin="-${a.toFixed(2)}s">\n                        <mpath href="#${e}"/>\n                    </animateMotion>\n                </circle>\n                <circle r="2.5" fill="${i}" opacity="0.9">\n                    <animateMotion dur="${o}s" repeatCount="indefinite" calcMode="paced"${n} begin="-${a.toFixed(2)}s">\n                        <mpath href="#${e}"/>\n                    </animateMotion>\n                </circle>`}return l}_updateGridColor(t,e){const i=this.renderRoot.getElementById("node-grid");i&&i.setAttribute("filter",`url(#glowGrid${e?"Import":"Export"})`);const s=this.renderRoot.getElementById("grid-circle");s&&(s.setAttribute("stroke",t),s.setAttribute("fill",this._hexToRgba(t,.07)));const r=this.renderRoot.querySelector("#node-grid .glow-ring");r&&r.setAttribute("stroke",t);const a=this.renderRoot.getElementById("grid-icon");a&&a.setAttribute("stroke",t);for(const e of["val-grid","label-grid","val-today-grid"]){const i=this.renderRoot.getElementById(e);i&&i.setAttribute("fill",t)}const o=this.renderRoot.getElementById("track-grid");o&&o.setAttribute("stroke",t)}_updateDeviceLabels(){const t=this.renderRoot.getElementById("device-labels");if(!t)return;const e=this._getDeviceList(),i=e.map(([t,e],i)=>`${e.power_entity}:${e.name}:${e.color||ht[i%ht.length]}:${e.icon_override||""}:${e.daily_energy_entity||""}`).join("|");this._deviceConfigSig!==i&&(this._deviceConfigSig=i,this._buildDeviceDOM(t,e)),this._updateDeviceValues(e)}_getDeviceList(){let t=[];if("entities"===this._mode&&this._entities?.individual)t=this._entities.individual.map((t,e)=>[t.entity||`device_${e}`,{name:t.name||t.entity?.split(".").pop()||`Device ${e+1}`,power_entity:t.entity,device_type:t.device_type||"appliance",is_on:!1,current_power:0,color:t.color,icon_override:t.icon,daily_energy_entity:t.daily_energy}]);else if("prefix"===this._mode){const e=this._hass.states[`${this._prefix}controllable_devices_count`];e?.attributes?.devices&&(t=Object.entries(e.attributes.devices).filter(([,t])=>t.power_entity||t.current_power>0).sort((t,e)=>(t[1].priority||5)-(e[1].priority||5)))}return t.slice(0,6)}_buildDeviceDOM(t,e){if(!e.length)return t.innerHTML="",void(this._devicePositions=[]);const i="'Segoe UI','Roboto',sans-serif",s=this._getLayout(),r=s.home,a=this._compact,o=a?26:24,n=a?2:Math.min(e.length,3),l=a?30:60,c=((a?500:1e3)-2*l)/n,d=s.deviceY,h=a?18:20;let p="";this._devicePositions=[],e.forEach(([t,e],s)=>{let g=e.name||t;g.length>h&&(g=g.substring(0,h-1)+"…");const _=e.color||ht[s%ht.length],u=this._deviceIcon(e.device_type,e.name||t),f=s%n,m=Math.floor(s/n),v=l+f*c+c/2,y=d+m*(a?100:90);this._devicePositions.push({cx:v,cy:y,nodeR:o,color:_}),p+=`<path id="dev-conn-${s}" d="M${r.cx},${r.cy+r.r} C${r.cx},${r.cy+r.r+30} ${v},${y-40} ${v},${y-o}" fill="none" stroke="${_}" stroke-width="1.2" stroke-dasharray="3,5" opacity="0.1"/>`,p+=`<g id="dev-flow-${s}"></g>`,p+=`<path id="dev-path-${s}" d="M${r.cx},${r.cy+r.r} C${r.cx},${r.cy+r.r+30} ${v},${y-40} ${v},${y-o}" fill="none" stroke="none"/>`;const x=e.power_entity?` data-entity="${e.power_entity}"`:"";p+=`<g id="dev-group-${s}" class="device-clickable"${x} data-idx="${s}">`,p+=`<circle id="dev-circle-${s}" cx="${v}" cy="${y}" r="${o}" fill="rgba(128,128,128,0.03)" stroke="${_}" stroke-width="1.2" opacity="0.4"/>`,p+=`<g transform="translate(${v},${y})" stroke="${_}" fill="none" opacity="0.35" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">${u}</g>`,p+=`<text x="${v}" y="${y+o+14}" text-anchor="middle" font-family="${i}" font-size="11" font-weight="500" fill="${_}" opacity="0.8">${this._escSvg(g)}</text>`,p+=`<text id="dev-val-${s}" x="${v}" y="${y+o+14+11+2}" text-anchor="middle" font-family="${i}" font-size="11" font-weight="600" fill="${_}" opacity="0.7">0 W</text>`,p+=`<text id="dev-daily-${s}" x="${v}" y="${y+o+14+26}" text-anchor="middle" font-family="${i}" font-size="11" fill="${_}" opacity="0.65"></text>`,p+="</g>"}),t.innerHTML=p,t.querySelectorAll(".device-clickable[data-entity]").forEach(t=>{const e=parseInt(t.dataset.idx);this._setupNodeActions(t,`device_${e}`,t.dataset.entity)}),e.forEach((t,e)=>{delete this._currentValues[`dev-val-${e}`]})}_updateDeviceValues(t){const e=this._getLayout().home;t.forEach(([t,i],s)=>{const r=i.power_entity?this._hass.states[i.power_entity]:null,a=r?parseFloat(r.state)||0:i.current_power||0,o=a>5,n=i.color||ht[s%ht.length],l=this._devicePositions[s];if(!l)return;if(this._animateValue(`dev-val-${s}`,a),i.daily_energy_entity){const t=this._hass.states[i.daily_energy_entity];this._setText(`dev-daily-${s}`,t?`${this._t("today")} ${t.state} kWh`:"")}const c=this.renderRoot.getElementById(`dev-conn-${s}`);c&&c.setAttribute("opacity",o?"0.3":"0.1");const d=this.renderRoot.getElementById(`dev-circle-${s}`);d&&(d.setAttribute("fill",`rgba(128,128,128,${o?.08:.03})`),d.setAttribute("opacity",o?"1":"0.4"));const h=this.renderRoot.getElementById(`dev-val-${s}`);h&&h.setAttribute("opacity",o?"1":"0.5");const p=this.renderRoot.getElementById(`dev-group-${s}`);if(p){const t=p.querySelector("g[transform]");t&&t.setAttribute("opacity",o?"0.7":"0.35")}const g=this.renderRoot.getElementById(`dev-flow-${s}`);if(g)if(a>5){const t=gt(a).toFixed(1);if(g.dataset.sig!==t){g.dataset.sig=t;const i=`M${e.cx},${e.cy+e.r} C${e.cx},${e.cy+e.r+30} ${l.cx},${l.cy-40} ${l.cx},${l.cy-l.nodeR}`;g.innerHTML=`\n                            <path d="${i}" fill="none" stroke="${n}" stroke-width="2" stroke-dasharray="8,16" opacity="0.4" stroke-linecap="round">\n                                <animate attributeName="stroke-dashoffset" from="0" to="-24" dur="${t}s" repeatCount="indefinite"/>\n                            </path>\n                            <circle r="2" fill="${n}" opacity="0.8">\n                                <animateMotion dur="${t}s" repeatCount="indefinite" calcMode="paced" begin="-${(.3*s).toFixed(1)}s">\n                                    <mpath href="#dev-path-${s}"/>\n                                </animateMotion>\n                            </circle>`}}else""!==g.dataset.sig&&(g.dataset.sig="",g.innerHTML="")})}_setupClickHandlers(){const t={"node-solar":"solar_power","val-solar":"solar_power","val-today-solar":"daily_solar_energy","node-battery":"battery_soc","val-battery-soc":"battery_soc","val-battery-power":"battery_power","label-battery-state":"battery_power","val-today-battery":"daily_battery_energy","node-grid":"grid_import_power","val-grid":"grid_import_power","label-grid":"grid_import_power","val-today-grid":"daily_grid_import_energy","node-home":"home_consumption_power","val-home":"home_consumption_power","val-autarky":"autarky_rate","val-today-home":"daily_home_energy","node-ev":"ev_power","val-ev":"ev_power","val-today-ev":"daily_ev_energy","val-inverter-status":"charging_state"};for(const[e,i]of Object.entries(t)){const t=this._getEntityId(i);if(!t)continue;const s=this.renderRoot.getElementById(e);s&&(s.setAttribute("data-entity",t),s.style.cursor="pointer")}const e=this.renderRoot.querySelector("svg");e&&!e._semClickBound&&(e._semClickBound=!0,e.addEventListener("click",t=>{let i=t.target;for(let t=0;t<5&&i&&i!==e;t++){const t=i.getAttribute?.("data-entity");if(t)return void this._fireMoreInfo(t);i=i.parentElement}}));const i=[{ids:["node-solar"],node:"solar",key:"solar_power"},{ids:["node-battery"],node:"battery",key:"battery_soc"},{ids:["node-grid"],node:"grid",key:"grid_import_power"},{ids:["node-home"],node:"home",key:"home_consumption_power"},{ids:["node-ev"],node:"ev",key:"ev_power"}];for(const{ids:t,node:e,key:s}of i){const i=this._getEntityId(s);if(i)for(const s of t){const t=this.renderRoot.getElementById(s);t&&!t._semActionsBound&&(t._semActionsBound=!0,t.classList.add("clickable-node"),this._setupNodeActions(t,e,i))}}}_setupNodeActions(t,e,i){let s=null,r=!1,a=0,o=null;t.style.cursor="pointer",t.addEventListener("pointerdown",()=>{r=!1,s=setTimeout(()=>{r=!0;const t=this._getActionConfig(e,"hold_action");"none"!==t.action&&this._handleAction(t,i)},500)}),t.addEventListener("pointerup",()=>clearTimeout(s)),t.addEventListener("pointercancel",()=>{clearTimeout(s),r=!1}),t.addEventListener("click",()=>{if(r)return void(r=!1);const t=this._getActionConfig(e,"double_tap_action");if(!t||"none"===t.action)return void this._handleAction(this._getActionConfig(e,"tap_action"),i);const s=Date.now();s-a<300?(clearTimeout(o),a=0,this._handleAction(t,i)):(a=s,o=setTimeout(()=>{a=0,this._handleAction(this._getActionConfig(e,"tap_action"),i)},300))})}_getActionConfig(t,e){const i=this._entities;if(!i)return{action:"tap_action"===e?"more-info":"none"};let s;if(t.startsWith("device_")){const e=parseInt(t.split("_")[1]);s=i.individual?.[e]}else{s={solar:i.solar,battery:i.battery,grid:i.grid,home:i.home,ev:i.ev||i.individual?.[0]}[t]}const r=s?.[e];return r?"string"==typeof r?{action:r}:r:{action:"tap_action"===e?"more-info":"none"}}_handleAction(t,e){switch(t||(t={action:"more-info"}),t.action){case"more-info":this._fireMoreInfo(t.entity||e);break;case"toggle":this._hass&&this._hass.callService("homeassistant","toggle",{entity_id:t.entity||e});break;case"navigate":t.navigation_path&&(window.history.pushState(null,"",t.navigation_path),window.dispatchEvent(new CustomEvent("location-changed")));break;case"call-service":if(t.service&&this._hass){const[e,i]=t.service.split(".");this._hass.callService(e,i,t.service_data||{})}break;case"url":t.url_path&&window.open(t.url_path,"_blank")}}_fireMoreInfo(t){t&&this.dispatchEvent(new CustomEvent("hass-more-info",{detail:{entityId:t},bubbles:!0,composed:!0}))}_setGlowIntensity(t,e,i){const s=this.renderRoot.querySelector(`#${t} .glow-ring`);if(!s)return;const r=Math.min(1,Math.abs(e)/i);s.style.opacity=(.15+.85*r).toFixed(2)}_animateValue(t,e,i=800,s=null){const r=this.renderRoot.getElementById(t);if(!r)return;this._animFrames[t]&&cancelAnimationFrame(this._animFrames[t]);const a=s||(t=>pt(t)),o=this._currentValues[t]||0;if(this._currentValues[t]=e,Math.abs(o-e)<.5)return void(r.textContent=a(e));const n=performance.now(),l=s=>{const c=Math.min(1,(s-n)/i),d=c<.5?2*c*c:1-Math.pow(-2*c+2,2)/2;r.textContent=a(o+(e-o)*d),c<1?this._animFrames[t]=requestAnimationFrame(l):delete this._animFrames[t]};this._animFrames[t]=requestAnimationFrame(l)}_setText(t,e){const i=this.renderRoot.getElementById(t);i&&(i.textContent=e)}_getState(t){if(!this._hass)return 0;const e="prefix"===this._mode?`${this._prefix}${t}`:this._resolveEntity(t);if(!e)return 0;const i=this._hass.states[e];if(!i)return 0;const s=parseFloat(i.state);return isNaN(s)?0:s}_getStateStr(t){if(!this._hass)return"";const e="prefix"===this._mode?`${this._prefix}${t}`:this._resolveEntity(t);if(!e)return"";const i=this._hass.states[e];return i?i.state:""}_getEntityId(t){return"prefix"===this._mode?`${this._prefix}${t}`:this._resolveEntity(t)}_resolveEntity(t){const e=this._entities;if(!e)return null;return{solar_power:e.solar?.entity,battery_power:e.battery?.entity,battery_charge_power:e.battery?.charge,battery_discharge_power:e.battery?.discharge,grid_power:e.grid?.entity,grid_import_power:e.grid?.consumption,grid_export_power:e.grid?.production,ev_power:e.ev?.entity||e.individual?.[0]?.entity,battery_soc:e.battery?.state_of_charge,home_consumption_power:e.home?.entity,charging_state:e.inverter?.entity,daily_solar_energy:e.solar?.daily_energy,daily_ev_energy:e.ev?.daily_energy||e.individual?.[0]?.daily_energy,daily_grid_import_energy:e.grid?.daily_import_energy,daily_grid_export_energy:e.grid?.daily_export_energy,daily_battery_energy:e.battery?.daily_energy,daily_home_energy:e.home?.daily_energy,autarky_rate:e.home?.autarky,ev_charger_count:e.ev?.charger_count||"sensor.sem_ev_charger_count"}[t]||null}_hasNode(t){if("prefix"===this._mode)return!0;const e=this._entities;if(!e)return!1;return{solar:!!e.solar?.entity,battery:!!(e.battery?.entity||e.battery?.charge||e.battery?.discharge),grid:!(!e.grid?.consumption&&!e.grid?.entity),home:!0,ev:!(!e.ev?.entity&&!e.individual?.[0]?.entity),inverter:!!e.inverter?.entity||!!e.solar?.entity}[t]||!1}_getNodeColor(t){const e=this._entities,i={solar:ce.solar.color,battery:ce.battery.color,grid:ce.grid.color_import,grid_import:ce.grid.color_import,grid_export:ce.grid.color_export,home:ce.home.color,ev:ce.ev.color,inverter:ce.inverter.color};if(!e)return i[t]||"#888";return{solar:e.solar?.color,battery:e.battery?.color,grid:e.grid?.color_import,grid_import:e.grid?.color_import,grid_export:e.grid?.color_export,home:e.home?.color,ev:e.ev?.color||e.individual?.[0]?.color}[t]||i[t]||"#888"}_getNodeName(t){const e=this._entities,i=ce[t]?.nameKey,s=i?this._t(i):t;if(!e)return s;return{solar:e.solar?.name,battery:e.battery?.name,grid:e.grid?.name,home:e.home?.name,ev:e.ev?.name||e.individual?.[0]?.name}[t]||s}_getLayout(){return this._compact?{vb:"0 0 500 1100",solar:{cx:250,cy:70,r:48},inverter:{cx:250,cy:225,r:20},battery:{cx:100,cy:340,r:48},grid:{cx:400,cy:340,r:48},home:{cx:250,cy:510,r:60},ev:{cx:100,cy:660,r:42},socR:33,autarkyR:48,paths:{solar:"M250,118 L250,205",home:"M250,245 L250,450",battery:"M230,230 C180,260 120,290 100,292",grid:"M270,230 C320,260 380,290 400,292",ev:"M230,240 C180,380 130,560 100,618"},font:{label:14,value:22,sub:12,homeVal:26},deviceY:810}:{vb:"0 0 1000 800",solar:{cx:500,cy:65,r:50},inverter:{cx:500,cy:210,r:20},battery:{cx:150,cy:270,r:50},grid:{cx:850,cy:270,r:50},home:{cx:500,cy:385,r:62},ev:{cx:150,cy:460,r:44},socR:40,autarkyR:50,paths:{solar:"M500,115 L500,190",home:"M500,230 L500,323",battery:"M480,215 C380,230 250,245 200,270",grid:"M520,215 C620,230 750,245 800,270",ev:"M480,225 C380,330 250,410 195,460"},font:{label:13,value:20,sub:11,homeVal:24},deviceY:590}}_glowFilter(t,e,i){return`<filter id="${t}" x="-30%" y="-30%" width="160%" height="160%">\n            <feGaussianBlur stdDeviation="${i}" result="blur"/>\n            <feFlood flood-color="${e}" flood-opacity="0.25"/>\n            <feComposite in2="blur" operator="in"/>\n            <feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge>\n        </filter>`}_glowRing(t,e,i=1.2){const s=t.r+5;return`<circle class="glow-ring" cx="${t.cx}" cy="${t.cy}" r="${s}" fill="none" stroke="${e}" stroke-width="${i}" opacity="0.3">\n            <animate attributeName="r" values="${s};${s+5};${s}" dur="3s" repeatCount="indefinite"/>\n            <animate attributeName="opacity" values="0.3;0.12;0.3" dur="3s" repeatCount="indefinite"/>\n        </circle>`}_track(t,e){return`<path d="${t}" fill="none" stroke="${e}" stroke-width="1.5" stroke-dasharray="4,6" opacity="0.18"/>`}_hexToRgba(t,e){const i=t.match(/^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i);return i?`rgba(${parseInt(i[1],16)},${parseInt(i[2],16)},${parseInt(i[3],16)},${e})`:`rgba(128,128,128,${e})`}_autarkyColor(t){if((t=Math.max(0,Math.min(100,t)))<=50){const e=t/50;return`rgb(220,${Math.round(50+150*e)},50)`}const e=(t-50)/50;return`rgb(${Math.round(220-170*e)},200,50)`}_deviceIcon(t,e){const i=(e||"").toLowerCase();return"ev_charger"===(t||"").toLowerCase()||i.includes("keba")||i.includes("charger")||i.includes("wallbox")?'<rect x="-6" y="-10" width="12" height="16" rx="2"/><path d="M-2,-4 L0,2 L2,-4"/><line x1="0" y1="6" x2="0" y2="10"/>':i.includes("heiz")||i.includes("heat")||i.includes("warm")||i.includes("boiler")?'<path d="M-4,-10 C-4,-4 4,-4 4,-10"/><path d="M-4,-3 C-4,3 4,3 4,-3"/><path d="M-4,4 C-4,10 4,10 4,4"/>':i.includes("wash")||i.includes("spül")||i.includes("geschirr")||i.includes("wasch")?'<circle r="10" fill="none"/><circle r="5" fill="none"/><circle r="1.5" fill="currentColor" opacity="0.3" stroke="none"/>':i.includes("dryer")||i.includes("trockn")?'<circle r="10" fill="none"/><path d="M-4,-4 C0,-8 0,8 4,4" fill="none"/>':i.includes("pool")||i.includes("pump")?'<circle r="8" fill="none"/><path d="M-6,0 L6,0 M0,-6 L0,6" opacity="0.5"/><path d="M-4,-4 L4,4 M4,-4 L-4,4"/>':i.includes("klima")||i.includes("ac")||i.includes("cool")||i.includes("air")?'<rect x="-10" y="-6" width="20" height="12" rx="2"/><path d="M-6,6 C-6,10 -2,10 -2,6" fill="none"/><path d="M2,6 C2,10 6,10 6,6" fill="none"/>':i.includes("light")||i.includes("licht")||i.includes("lamp")?'<path d="M-5,-10 C-8,-2 -3,4 -2,6 L2,6 C3,4 8,-2 5,-10 C2,-14 -2,-14 -5,-10Z" fill="none"/><line x1="-2" y1="8" x2="2" y2="8"/>':i.includes("shelly")||i.includes("plug")||i.includes("switch")||i.includes("steckdose")?'<rect x="-8" y="-10" width="16" height="20" rx="3"/><circle cx="-3" cy="-2" r="2" fill="none"/><circle cx="3" cy="-2" r="2" fill="none"/><line x1="0" y1="4" x2="0" y2="7"/>':'<path d="M-3,-10 L-3,0 L-6,0 L0,10 L0,0 L3,0 L-3,-10Z" fill="none"/>'}getCardSize(){return 8}static async getConfigElement(){return document.createElement("sem-flow-card-editor")}static getStubConfig(t){const e=t?Object.keys(t.states):[],i=t=>{for(const i of t){const t=e.find(t=>t.includes(i));if(t)return t}return null};return{entities:{solar:{entity:i(["solar_power","pv_power"])||"sensor.solar_power"},grid:{consumption:i(["grid_import","grid_consumption"])||"sensor.grid_import_power",production:i(["grid_export","grid_feed"])||"sensor.grid_export_power"},battery:{entity:i(["battery_power","batt_power"])||"sensor.battery_power",state_of_charge:i(["battery_soc","battery_level"])||"sensor.battery_soc"},home:{entity:i(["home_consumption","house_power"])||"sensor.home_consumption_power"}}}}},{type:"sem-flow-card",name:"SEM Flow Card",description:"Animated energy flow diagram — works with any HA entities"});ft("sem-system-diagram-card",class extends mt{constructor(){super(),this._lastKey="",this._animFrames={},this._currentValues={},this._compact=!1,this._visible=!0,this._updateTimer=null,this._resizeObserver=null,this._intersectionObserver=null,this._resizeTimeout=null}setConfig(t){this._config=t,this.entityPrefix=t.entity_prefix||"sensor.sem_",this.requestUpdate()}set hass(t){this._hass,this._hass=t;const e=t?.language;if(e!==this._lang)return this._lang=e,this._lastKey="",void this.requestUpdate();this._visible&&(clearTimeout(this._updateTimer),this._updateTimer=setTimeout(()=>this._updateFlowsImperative(),100))}get hass(){return this._hass}firstUpdated(){this._resizeObserver=new ResizeObserver(t=>{this._resizeTimeout&&clearTimeout(this._resizeTimeout),this._resizeTimeout=setTimeout(()=>{for(const e of t){const t=e.contentRect.width<500;t!==this._compact&&(this._compact=t,this._lastKey="",this.requestUpdate())}},100)}),this._resizeObserver.observe(this),this._intersectionObserver=new IntersectionObserver(t=>{this._visible=t[0].isIntersecting;const e=this.renderRoot.querySelector("svg");e&&(e.style.animationPlayState=this._visible?"running":"paused")},{threshold:.01}),this._intersectionObserver.observe(this)}disconnectedCallback(){super.disconnectedCallback(),this._resizeObserver&&(this._resizeObserver.disconnect(),this._resizeObserver=null),this._intersectionObserver&&(this._intersectionObserver.disconnect(),this._intersectionObserver=null),clearTimeout(this._updateTimer),clearTimeout(this._resizeTimeout);for(const t of Object.keys(this._animFrames))cancelAnimationFrame(this._animFrames[t]);this._animFrames={}}updated(){this._updateFlowsImperative()}static get styles(){return a`
            :host { display: block; }
            ha-card { overflow: hidden; padding: 0; background: transparent !important; }
            svg { width: 100%; display: block; }
            .flow-group { transition: opacity 0.8s cubic-bezier(0.4,0,0.2,1); }
            .glow-ring { transition: opacity 1s ease; }
            #soc-arc, #sc-arc { transition: stroke-dashoffset 1.5s cubic-bezier(0.4,0,0.2,1); }
            text { font-variant-numeric: tabular-nums; }
            @keyframes socPulse { 0%,100%{opacity:1} 50%{opacity:0.6} }
        `}render(){if(!this._config)return K;const t=this._getLayout(),e=t.solar,i=t.inverter,s=t.battery,r=t.grid,a=t.home,o=t.ev,n=(2*Math.PI*t.socR).toFixed(1),l=a.r-8,c=(2*Math.PI*l).toFixed(1),d=t.font.label,h=t.font.value,p=t.font.sub,g=t.font.homeVal,_="'Segoe UI','Roboto',sans-serif";return H`
            <ha-card>
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="${t.vb}" style="background:transparent"
                     role="img" aria-label="Solar energy system diagram">
                    <defs>
                        <radialGradient id="bgGrad" cx="50%" cy="45%" r="60%">
                            <stop offset="0%" stop-color="rgba(200,220,240,0.08)"/>
                            <stop offset="100%" stop-color="rgba(0,0,0,0)"/>
                        </radialGradient>
                        <pattern id="dotGrid" width="50" height="50" patternUnits="userSpaceOnUse">
                            <circle cx="25" cy="25" r="0.7" fill="rgba(128,128,128,0.08)"/>
                        </pattern>
                        ${this._svgGlowFilter("glowSolar","#ff9800",8)}
                        ${this._svgGlowFilter("glowBattery","#4db6ac",8)}
                        ${this._svgGlowFilter("glowGrid","#488fc2",8)}
                        ${this._svgGlowFilter("glowHome","#5BC8D8",10)}
                        ${this._svgGlowFilter("glowEV","#8DC892",8)}
                        ${this._svgGlowFilter("glowInverter","#96CAEE",6)}
                        <path id="path-solar"   d="${t.paths.solar}"/>
                        <path id="path-home"    d="${t.paths.home}"/>
                        <path id="path-battery" d="${t.paths.battery}"/>
                        <path id="path-grid"    d="${t.paths.grid}"/>
                        <path id="path-ev"      d="${t.paths.ev}"/>
                    </defs>

                    <rect width="100%" height="100%" fill="url(#bgGrad)"/>
                    <rect width="100%" height="90%"  fill="url(#dotGrid)"/>

                    <!-- Static tracks -->
                    <path d="${t.paths.solar}"   fill="none" stroke="#ff9800" stroke-width="1.5" stroke-dasharray="4,6" opacity="0.18"/>
                    <path d="${t.paths.home}"    fill="none" stroke="#5BC8D8" stroke-width="1.5" stroke-dasharray="4,6" opacity="0.18"/>
                    <path d="${t.paths.battery}" fill="none" stroke="#4db6ac" stroke-width="1.5" stroke-dasharray="4,6" opacity="0.18"/>
                    <path d="${t.paths.grid}"    fill="none" stroke="#488fc2" stroke-width="1.5" stroke-dasharray="4,6" opacity="0.18"/>
                    <path d="${t.paths.ev}"      fill="none" stroke="#8DC892" stroke-width="1.5" stroke-dasharray="4,6" opacity="0.18"/>

                    <!-- Flow groups -->
                    <g id="flow-solar"   class="flow-group" style="opacity:0" data-path-id="path-solar"   data-path-d="${t.paths.solar}"   data-color="#ff9800" data-count="2"></g>
                    <g id="flow-battery" class="flow-group" style="opacity:0" data-path-id="path-battery" data-path-d="${t.paths.battery}" data-color="#4db6ac" data-count="3"></g>
                    <g id="flow-grid"    class="flow-group" style="opacity:0" data-path-id="path-grid"    data-path-d="${t.paths.grid}"    data-color="#488fc2" data-count="3"></g>
                    <g id="flow-home"    class="flow-group" style="opacity:0" data-path-id="path-home"    data-path-d="${t.paths.home}"    data-color="#5BC8D8" data-count="2"></g>
                    <g id="flow-ev"      class="flow-group" style="opacity:0" data-path-id="path-ev"      data-path-d="${t.paths.ev}"      data-color="#8DC892" data-count="3"></g>

                    <!-- SOLAR -->
                    <g id="node-solar" filter="url(#glowSolar)">
                        <circle class="glow-ring" cx="${e.cx}" cy="${e.cy}" r="${e.r+5}" fill="none" stroke="#ff9800" stroke-width="1.2" opacity="0.3">
                            <animate attributeName="r" values="${e.r+5};${e.r+10};${e.r+5}" dur="3s" repeatCount="indefinite"/>
                            <animate attributeName="opacity" values="0.3;0.12;0.3" dur="3s" repeatCount="indefinite"/>
                        </circle>
                        <circle cx="${e.cx}" cy="${e.cy}" r="${e.r}" fill="rgba(255,152,0,0.07)" stroke="#ff9800" stroke-width="1.8"/>
                        <g transform="translate(${e.cx},${e.cy-8})" stroke="#ff9800" fill="none" opacity="0.75">
                            <rect x="-16" y="-12" width="32" height="24" rx="3" stroke-width="1.8"/>
                            <line x1="-16" y1="0" x2="16" y2="0" stroke-width="1.2"/>
                            <line x1="-5" y1="-12" x2="-5" y2="12" stroke-width="1.2"/>
                            <line x1="5" y1="-12" x2="5" y2="12" stroke-width="1.2"/>
                            <line x1="0" y1="12" x2="0" y2="17" stroke-width="1.5"/>
                            <line x1="-7" y1="17" x2="7" y2="17" stroke-width="1.5"/>
                        </g>
                    </g>
                    <text id="label-solar" x="${e.cx}" y="${e.cy+e.r+18}" text-anchor="middle" font-family="${_}" font-size="${d}" font-weight="600" fill="#ff9800">${this._t("solar")}</text>
                    <text id="val-solar" x="${e.cx}" y="${e.cy+e.r+18+.9*h}" text-anchor="middle" font-family="${_}" font-size="${h}" font-weight="700" fill="#ff9800">0 W</text>
                    <text id="val-today-solar" x="${e.cx}" y="${e.cy+e.r+18+.9*h+p+4}" text-anchor="middle" font-family="${_}" font-size="${p}" fill="#ff9800" opacity="0.55"></text>
                    <text id="val-forecast" x="${e.cx+e.r+10}" y="${e.cy-e.r+5}" text-anchor="start" font-family="${_}" font-size="${p}" fill="#ff9800" opacity="0.5"></text>

                    <!-- INVERTER -->
                    <g id="node-inverter" filter="url(#glowInverter)">
                        <circle cx="${i.cx}" cy="${i.cy}" r="${i.r}" fill="rgba(150,202,238,0.07)" stroke="#96CAEE" stroke-width="1"/>
                        <path d="M${i.cx-10},${i.cy} Q${i.cx-4},${i.cy-8} ${i.cx},${i.cy} Q${i.cx+4},${i.cy+8} ${i.cx+10},${i.cy}" fill="none" stroke="#96CAEE" stroke-width="1.8" opacity="0.7"/>
                    </g>
                    <text id="val-inverter-status" x="${i.cx}" y="${i.cy+i.r+14}" text-anchor="middle" font-family="${_}" font-size="${this._compact?11:10}" fill="#5a7a9a" opacity="0.7"></text>

                    <!-- BATTERY -->
                    <g id="node-battery" filter="url(#glowBattery)">
                        <circle class="glow-ring" cx="${s.cx}" cy="${s.cy}" r="${s.r+5}" fill="none" stroke="#4db6ac" stroke-width="1.2" opacity="0.3">
                            <animate attributeName="r" values="${s.r+5};${s.r+10};${s.r+5}" dur="3s" repeatCount="indefinite"/>
                            <animate attributeName="opacity" values="0.3;0.12;0.3" dur="3s" repeatCount="indefinite"/>
                        </circle>
                        <circle cx="${s.cx}" cy="${s.cy}" r="${s.r}" fill="rgba(77,182,172,0.07)" stroke="#4db6ac" stroke-width="1.8"/>
                        <circle cx="${s.cx}" cy="${s.cy}" r="${t.socR}" fill="none" stroke="rgba(77,182,172,0.1)" stroke-width="5"/>
                        <circle id="soc-arc" cx="${s.cx}" cy="${s.cy}" r="${t.socR}" fill="none" stroke="#4db6ac" stroke-width="5"
                                stroke-dasharray="${n}" stroke-dashoffset="${n}"
                                transform="rotate(-90 ${s.cx} ${s.cy})" stroke-linecap="round" opacity="0.75"/>
                        <g transform="translate(${s.cx},${s.cy})" stroke="#4db6ac" fill="none" opacity="0.7">
                            <rect x="-8" y="-13" width="16" height="26" rx="3" stroke-width="1.8"/>
                            <rect x="-3" y="-16" width="6" height="4" rx="1.5" fill="#4db6ac" opacity="0.5" stroke="none"/>
                        </g>
                    </g>
                    <text id="label-battery" x="${s.cx}" y="${s.cy+s.r+18}" text-anchor="middle" font-family="${_}" font-size="${d}" font-weight="600" fill="#4db6ac">${this._t("battery")}</text>
                    <text id="val-battery-soc" x="${s.cx}" y="${s.cy+s.r+18+.9*h}" text-anchor="middle" font-family="${_}" font-size="${h}" font-weight="700" fill="#4db6ac">0%</text>
                    <text id="val-battery-power" x="${s.cx}" y="${s.cy+s.r+18+.9*h+d}" text-anchor="middle" font-family="${_}" font-size="${d}" font-weight="500" fill="#4db6ac" opacity="0.7">0 W</text>
                    <text id="label-battery-state" x="${s.cx}" y="${s.cy+s.r+18+.9*h+2*d}" text-anchor="middle" font-family="${_}" font-size="${p}" fill="#4db6ac" opacity="0.5"></text>
                    <text id="val-today-battery" x="${s.cx}" y="${s.cy+s.r+18+.9*h+2*d+p+2}" text-anchor="middle" font-family="${_}" font-size="${p}" fill="#4db6ac" opacity="0.4"></text>

                    <!-- GRID -->
                    <g id="node-grid" filter="url(#glowGrid)">
                        <circle class="glow-ring" cx="${r.cx}" cy="${r.cy}" r="${r.r+5}" fill="none" stroke="#488fc2" stroke-width="1.2" opacity="0.3">
                            <animate attributeName="r" values="${r.r+5};${r.r+10};${r.r+5}" dur="3s" repeatCount="indefinite"/>
                            <animate attributeName="opacity" values="0.3;0.12;0.3" dur="3s" repeatCount="indefinite"/>
                        </circle>
                        <circle cx="${r.cx}" cy="${r.cy}" r="${r.r}" fill="rgba(72,143,194,0.07)" stroke="#488fc2" stroke-width="1.8"/>
                        <g transform="translate(${r.cx},${r.cy})" stroke="#488fc2" fill="none" opacity="0.7" stroke-width="1.8" stroke-linecap="round">
                            <line x1="0" y1="-16" x2="0" y2="14"/>
                            <line x1="-10" y1="-8" x2="10" y2="-8"/>
                            <line x1="-7" y1="-1" x2="7" y2="-1"/>
                            <line x1="-10" y1="-8" x2="-5" y2="14"/>
                            <line x1="10" y1="-8" x2="5" y2="14"/>
                        </g>
                    </g>
                    <text id="label-grid-name" x="${r.cx}" y="${r.cy+r.r+18}" text-anchor="middle" font-family="${_}" font-size="${d}" font-weight="600" fill="#488fc2">${this._t("grid")}</text>
                    <text id="val-grid-single" x="${r.cx}" y="${r.cy+r.r+18+.9*h}" text-anchor="middle" font-family="${_}" font-size="${h}" font-weight="700" fill="#488fc2">0 W</text>
                    <text id="val-grid-import" x="${r.cx}" y="${r.cy+r.r+18+.9*h}" text-anchor="middle" font-family="${_}" font-size="${.8*h}" font-weight="700" fill="#488fc2" style="display:none">↓ 0 W</text>
                    <text id="val-grid-export" x="${r.cx}" y="${r.cy+r.r+18+.9*h+.7*h}" text-anchor="middle" font-family="${_}" font-size="${.8*h}" font-weight="700" fill="#8353d1" style="display:none">↑ 0 W</text>
                    <text id="label-grid" x="${r.cx}" y="${r.cy+r.r+18+.9*h+d}" text-anchor="middle" font-family="${_}" font-size="${p}" font-weight="500" fill="#488fc2" opacity="0.5">GRID</text>
                    <text id="val-today-grid" x="${r.cx}" y="${r.cy+r.r+18+.9*h+d+p+2}" text-anchor="middle" font-family="${_}" font-size="${p}" fill="#488fc2" opacity="0.45"></text>

                    <!-- HOME (central hub) -->
                    <g id="node-home" filter="url(#glowHome)">
                        <circle class="glow-ring" cx="${a.cx}" cy="${a.cy}" r="${a.r+5}" fill="none" stroke="#5BC8D8" stroke-width="1.4" opacity="0.3">
                            <animate attributeName="r" values="${a.r+5};${a.r+10};${a.r+5}" dur="3s" repeatCount="indefinite"/>
                            <animate attributeName="opacity" values="0.3;0.12;0.3" dur="3s" repeatCount="indefinite"/>
                        </circle>
                        <circle cx="${a.cx}" cy="${a.cy}" r="${a.r}" fill="rgba(91,200,216,0.06)" stroke="#5BC8D8" stroke-width="2"/>
                        <circle cx="${a.cx}" cy="${a.cy}" r="${l}" fill="none" stroke="rgba(91,200,216,0.1)" stroke-width="4"/>
                        <circle id="sc-arc" cx="${a.cx}" cy="${a.cy}" r="${l}" fill="none" stroke="#5BC8D8" stroke-width="4"
                                stroke-dasharray="${c}" stroke-dashoffset="${c}"
                                transform="rotate(-90 ${a.cx} ${a.cy})" stroke-linecap="round" opacity="0.6"/>
                        <g transform="translate(${a.cx},${a.cy-5})" stroke="#5BC8D8" fill="none" opacity="0.6" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M-20,2 L0,-14 L20,2"/>
                            <rect x="-14" y="2" width="28" height="20" rx="2"/>
                            <rect x="-4" y="10" width="8" height="12"/>
                        </g>
                        <text id="val-self-consumption" x="${a.cx}" y="${a.cy+a.r-20}" text-anchor="middle" font-family="${_}" font-size="${p-1}" font-weight="600" fill="#5BC8D8" opacity="0.5"></text>
                    </g>
                    <text id="label-home" x="${a.cx}" y="${a.cy+a.r+18}" text-anchor="middle" font-family="${_}" font-size="${d+1}" font-weight="600" fill="#5BC8D8">${this._t("home")}</text>
                    <text id="val-home" x="${a.cx}" y="${a.cy+a.r+18+.9*g}" text-anchor="middle" font-family="${_}" font-size="${g}" font-weight="700" fill="#5BC8D8">0 W</text>
                    <text id="val-autarky" x="${a.cx}" y="${a.cy+a.r+18+.9*g+p+4}" text-anchor="middle" font-family="${_}" font-size="${p}" fill="#5BC8D8" opacity="0.5"></text>
                    <text id="val-today-home" x="${a.cx}" y="${a.cy+a.r+18+.9*g+2*p+6}" text-anchor="middle" font-family="${_}" font-size="${p}" fill="#5BC8D8" opacity="0.4"></text>

                    <!-- EV -->
                    <g id="node-ev" filter="url(#glowEV)">
                        <circle class="glow-ring" cx="${o.cx}" cy="${o.cy}" r="${o.r+5}" fill="none" stroke="#8DC892" stroke-width="1.2" opacity="0.3">
                            <animate attributeName="r" values="${o.r+5};${o.r+10};${o.r+5}" dur="3s" repeatCount="indefinite"/>
                            <animate attributeName="opacity" values="0.3;0.12;0.3" dur="3s" repeatCount="indefinite"/>
                        </circle>
                        <circle cx="${o.cx}" cy="${o.cy}" r="${o.r}" fill="rgba(141,200,146,0.07)" stroke="#8DC892" stroke-width="1.8"/>
                        <g transform="translate(${o.cx},${o.cy})" stroke="#8DC892" fill="none" opacity="0.7" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                            <rect x="-8" y="-13" width="16" height="22" rx="3"/>
                            <rect x="-5" y="-9" width="10" height="8" rx="1.5"/>
                            <path d="M-1,-1 L0,3 L1,-1"/>
                            <line x1="0" y1="9" x2="0" y2="13"/>
                            <circle cx="0" cy="15" r="1.5" fill="#8DC892" opacity="0.4" stroke="none"/>
                        </g>
                    </g>
                    <text id="label-ev" x="${o.cx}" y="${o.cy+o.r+18}" text-anchor="middle" font-family="${_}" font-size="${d}" font-weight="600" fill="#8DC892">${this._t("ev_charging")}</text>
                    <text id="val-ev" x="${o.cx}" y="${o.cy+o.r+18+.9*h}" text-anchor="middle" font-family="${_}" font-size="${h}" font-weight="700" fill="#8DC892">0 W</text>
                    <text id="val-today-ev" x="${o.cx}" y="${o.cy+o.r+18+.9*h+p+4}" text-anchor="middle" font-family="${_}" font-size="${p}" fill="#8DC892" opacity="0.5"></text>

                    <!-- Device labels (populated imperatively) -->
                    <g id="device-labels"></g>

                    <!-- Entity status indicator -->
                    <foreignObject x="10" y="${this._compact?1030:750}" width="200" height="20">
                        <div xmlns="http://www.w3.org/1999/xhtml" id="entity-status"
                             style="display:none;font-family:'Segoe UI','Roboto',sans-serif;font-size:10px;color:#ef5350;opacity:0.7"></div>
                    </foreignObject>

                    <!-- SEM watermark -->
                    <text x="${this._compact?470:960}" y="${this._compact?1050:770}" text-anchor="end"
                          font-family="${_}" font-size="10" font-weight="300" letter-spacing="2" fill="rgba(0,0,0,0.1)">SEM</text>
                </svg>
            </ha-card>
        `}_updateFlowsImperative(){if(!this._hass)return;const t=this._getState("solar_power"),e=this._getState("battery_power"),i=this._getState("grid_import_power"),s=this._getState("grid_export_power"),r=this._getState("ev_power"),a=this._getState("battery_soc"),o=Math.max(0,e),n=Math.max(0,-e),l=Math.max(0,t+i+n-s-o-r),c={solar:t,battery:e,gridImport:i,gridExport:s,home:l,ev:r,soc:a},d=JSON.stringify(c);if(this._lastKey===d)return;this._lastKey=d;const h=[];for(const t of["solar_power","battery_power","grid_import_power","grid_export_power","ev_power","battery_soc"]){const e=this._hass.states[`${this.entityPrefix}${t}`];e&&"unavailable"!==e.state&&"unknown"!==e.state||h.push(t)}const p=this.renderRoot.getElementById("entity-status");p&&(h.length>0?(p.textContent=`⚠ ${h.length} ${this._t("sensor_unavailable")}`,p.style.display="block"):p.style.display="none"),this._animateValue("val-solar",t),this._animateValue("val-battery-power",Math.abs(e)),this._animateValue("val-home",l),this._animateValue("val-ev",r),this._animateValue("val-grid-import",i,800,t=>`↓ ${pt(t)}`),this._animateValue("val-grid-export",s,800,t=>`↑ ${pt(t)}`);const g=this.renderRoot.getElementById("val-grid-import"),_=this.renderRoot.getElementById("val-grid-export"),u=this.renderRoot.getElementById("val-grid-single");g&&(g.style.display=i>10?"block":"none"),_&&(_.style.display=s>10?"block":"none"),u&&(u.style.display=i<=10&&s<=10?"block":"none"),this._setText("val-battery-soc",`${a.toFixed(0)}%`),this._setText("val-inverter-status",this._getStateStr("charging_state")),this._setText("val-today-solar",`${this._t("today")} ${this._getStateStr("daily_solar_energy")} kWh`),this._setText("val-today-ev",`${this._t("today")} ${this._getStateStr("daily_ev_energy")} kWh`);const f=this._getState("daily_battery_charge_energy"),m=this._getState("daily_battery_discharge_energy");this._setText("val-today-battery",`+${f.toFixed(1)} / -${m.toFixed(1)} kWh`);const v=this._getState("daily_grid_import_energy"),y=this._getState("daily_grid_export_energy");this._setText("val-today-grid",`↓${v.toFixed(1)} / ↑${y.toFixed(1)} kWh`),this._setText("val-today-home",`${this._t("today")} ${this._getState("daily_home_energy").toFixed(1)} kWh`);const x=this._getState("autarky_rate"),b=this._getState("self_consumption_rate");this._setText("val-autarky",`${this._t("autarky")} ${x.toFixed(0)}%`);const $=this.renderRoot.getElementById("sc-arc");if($){const t=this._getLayout().home.r-8,e=(2*Math.PI*t*(1-b/100)).toFixed(1);$.style.strokeDashoffset!==e&&($.style.strokeDashoffset=e)}this._setText("val-self-consumption",`${b.toFixed(0)}%`);const w=this._getState("forecast_remaining_today_kwh");this._setText("val-forecast",w>0?`☀ ${w.toFixed(1)} kWh left`:"");const k=this.renderRoot.getElementById("soc-arc");if(k){const t=((this._compact?207.3:251.3)*(1-a/100)).toFixed(1);k.style.strokeDashoffset!==t&&(k.style.strokeDashoffset=t);const e=o>10?"socPulse 2s ease-in-out infinite":"none";k.style.animation!==e&&(k.style.animation=e)}const S=this.renderRoot.getElementById("label-grid");S&&(S.textContent=i>s?this._t("importing"):s>10?this._t("exporting"):this._t("grid"));const C=this.renderRoot.getElementById("label-battery-state");C&&(o>10?(C.textContent=this._t("charging"),C.setAttribute("fill","#f06292")):n>10?(C.textContent=this._t("discharging"),C.setAttribute("fill","#4db6ac")):C.textContent=""),this._updateFlow("flow-solar",t>10,!1,gt(t)),this._updateFlow("flow-battery",Math.abs(e)>10,e<0,gt(e));const E=this.renderRoot.getElementById("flow-battery");E&&(E.dataset.color=o>10?"#f06292":"#4db6ac"),this._updateFlow("flow-grid",i>10||s>10,i>s,gt(i||s)),this._updateFlow("flow-home",l>10,!1,gt(l)),this._updateFlow("flow-ev",r>10,!1,gt(r)),this._setGlowIntensity("node-solar",t,1e4),this._setGlowIntensity("node-battery",Math.abs(e),5e3),this._setGlowIntensity("node-grid",Math.max(i,s),1e4),this._setGlowIntensity("node-home",l,8e3),this._setGlowIntensity("node-ev",r,11e3),this._updateDeviceLabels()}_updateFlow(t,e,i,s){const r=this.renderRoot.getElementById(t);if(!r)return;if(r.style.opacity=e?"1":"0",!e)return void(r.dataset.sig="");const a=r.dataset.pathId,o=r.dataset.pathD,n=r.dataset.color,l=parseInt(r.dataset.count,10)||2,c=`${i?"r":"f"}:${s.toFixed(1)}`;r.dataset.sig!==c&&(r.dataset.sig=c,r.innerHTML=this._flowEffects(o,a,n,l,s,i))}_flowEffects(t,e,i,s,r,a){const o=r.toFixed(1),n=a?' keyPoints="1;0" keyTimes="0;1"':"";let l=`<path d="${t}" fill="none" stroke="${i}" stroke-width="3"\n                     stroke-dasharray="12,20" opacity="0.5" stroke-linecap="round">\n                     <animate attributeName="stroke-dashoffset" from="0" to="${a?"32":"-32"}"\n                              dur="${o}s" repeatCount="indefinite"/>\n                   </path>`;for(let t=0;t<s;t++){const a=t/s*r;l+=`\n                <circle r="5" fill="${i}" opacity="0.12">\n                    <animateMotion dur="${o}s" repeatCount="indefinite" calcMode="paced"${n} begin="-${a.toFixed(2)}s">\n                        <mpath href="#${e}"/>\n                    </animateMotion>\n                </circle>\n                <circle r="2.5" fill="${i}" opacity="0.9">\n                    <animateMotion dur="${o}s" repeatCount="indefinite" calcMode="paced"${n} begin="-${a.toFixed(2)}s">\n                        <mpath href="#${e}"/>\n                    </animateMotion>\n                </circle>`}return l}_updateDeviceLabels(){const t=this.renderRoot.getElementById("device-labels");if(!t)return;const e=this._hass.states[`${this.entityPrefix}controllable_devices_count`];if(!e?.attributes?.devices)return void(t.innerHTML="");const i=ht,s=Object.entries(e.attributes.devices).filter(([,t])=>t.power_entity||t.current_power>0).sort((t,e)=>(t[1].priority||5)-(e[1].priority||5)).slice(0,6);if(!s.length)return void(t.innerHTML="");const r="'Segoe UI','Roboto',sans-serif",a=this._compact,o=this._getLayout(),n=o.home,l=a?26:24,c=a?2:Math.min(s.length,3),d=a?30:60,h=((a?500:1e3)-2*d)/c,p=o.deviceY,g=a?18:20;let _="";s.forEach(([t,e],s)=>{let o=e.name||t;o.length>g&&(o=o.substring(0,g-1)+"…");const u=e.power_entity?this._hass.states[e.power_entity]:null,f=u?parseFloat(u.state)||0:e.current_power||0,m=i[s%i.length],v=e.is_on||f>5,y=s%c,x=Math.floor(s/c),b=d+y*h+h/2,$=p+x*(a?100:90),w=this._deviceIcon(e.device_type,e.name||t),k=v?.3:.1;if(_+=`<path d="M${n.cx},${n.cy+n.r} C${n.cx},${n.cy+n.r+30} ${b},${$-40} ${b},${$-l}"\n                               fill="none" stroke="${m}" stroke-width="1.2" stroke-dasharray="3,5" opacity="${k}"/>`,f>5){const t=gt(f).toFixed(1);_+=`<path d="M${n.cx},${n.cy+n.r} C${n.cx},${n.cy+n.r+30} ${b},${$-40} ${b},${$-l}"\n                                   fill="none" stroke="${m}" stroke-width="2" stroke-dasharray="8,16" opacity="0.4" stroke-linecap="round">\n                                 <animate attributeName="stroke-dashoffset" from="0" to="-24" dur="${t}s" repeatCount="indefinite"/>\n                               </path>\n                               <circle r="2" fill="${m}" opacity="0.8">\n                                   <animateMotion dur="${t}s" repeatCount="indefinite" calcMode="paced" begin="-${(.3*s).toFixed(1)}s">\n                                       <mpath href="#dev-path-${s}"/>\n                                   </animateMotion>\n                               </circle>\n                               <path id="dev-path-${s}" d="M${n.cx},${n.cy+n.r} C${n.cx},${n.cy+n.r+30} ${b},${$-40} ${b},${$-l}" fill="none" stroke="none"/>`}_+=`<circle cx="${b}" cy="${$}" r="${l}" fill="rgba(128,128,128,${v?.08:.03})" stroke="${m}" stroke-width="1.2" opacity="${v?1:.4}"/>`,_+=`<g transform="translate(${b},${$})" stroke="${m}" fill="none" opacity="${v?.7:.35}" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">${w}</g>`,_+=`<text x="${b}" y="${$+l+14}" text-anchor="middle" font-family="${r}" font-size="11" font-weight="500" fill="${m}" opacity="0.8">${o}</text>`,_+=`<text x="${b}" y="${$+l+14+11+2}" text-anchor="middle" font-family="${r}" font-size="11" font-weight="600" fill="${m}" opacity="${v?1:.5}">${pt(f)}</text>`}),t.innerHTML=_}_setGlowIntensity(t,e,i){const s=this.renderRoot.querySelector(`#${t} .glow-ring`);if(!s)return;const r=(.15+.85*Math.min(1,Math.abs(e)/i)).toFixed(2);s.style.opacity!==r&&(s.style.opacity=r)}_animateValue(t,e,i=800,s=null){const r=this.renderRoot.getElementById(t);if(!r)return;this._animFrames[t]&&cancelAnimationFrame(this._animFrames[t]);const a=s||(t=>pt(t)),o=this._currentValues[t]||0;if(this._currentValues[t]=e,Math.abs(o-e)<1)return void(r.textContent=a(e));const n=performance.now(),l=s=>{const c=Math.min(1,(s-n)/i),d=c<.5?2*c*c:1-Math.pow(-2*c+2,2)/2;r.textContent=a(o+(e-o)*d),c<1?this._animFrames[t]=requestAnimationFrame(l):delete this._animFrames[t]};this._animFrames[t]=requestAnimationFrame(l)}_setText(t,e){const i=this.renderRoot.getElementById(t);i&&i.textContent!==e&&(i.textContent=e)}_getState(t){if(!this._hass)return 0;const e=this._hass.states[`${this.entityPrefix}${t}`];if(!e)return 0;const i=parseFloat(e.state);return isNaN(i)?0:i}_getStateStr(t){if(!this._hass)return"";const e=this._hass.states[`${this.entityPrefix}${t}`];return e?e.state:""}_getLayout(){return this._compact?{vb:"0 0 500 1060",solar:{cx:250,cy:70,r:48},inverter:{cx:250,cy:195,r:20},battery:{cx:100,cy:310,r:48},grid:{cx:400,cy:310,r:48},home:{cx:250,cy:480,r:60},ev:{cx:100,cy:630,r:42},socR:33,paths:{solar:"M250,118 L250,175",home:"M250,215 L250,420",battery:"M230,200 C180,230 120,260 100,262",grid:"M270,200 C320,230 380,260 400,262",ev:"M230,210 C180,350 130,530 100,588"},font:{label:14,value:22,sub:12,homeVal:26},deviceY:780}:{vb:"0 0 1000 780",solar:{cx:500,cy:65,r:50},inverter:{cx:500,cy:185,r:20},battery:{cx:150,cy:240,r:50},grid:{cx:850,cy:240,r:50},home:{cx:500,cy:355,r:62},ev:{cx:150,cy:430,r:44},socR:40,paths:{solar:"M500,115 L500,165",home:"M500,205 L500,293",battery:"M480,190 C380,200 250,215 200,240",grid:"M520,190 C620,200 750,215 800,240",ev:"M480,198 C380,300 250,380 195,430"},font:{label:13,value:20,sub:11,homeVal:24},deviceY:560}}_svgGlowFilter(t,e,i){return H`<filter id="${t}" x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur stdDeviation="${i}" result="blur"/>
            <feFlood flood-color="${e}" flood-opacity="0.25"/>
            <feComposite in2="blur" operator="in"/>
            <feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge>
        </filter>`}_deviceIcon(t,e){const i=(e||"").toLowerCase();return"ev_charger"===(t||"").toLowerCase()||i.includes("keba")||i.includes("charger")||i.includes("wallbox")?'<rect x="-6" y="-10" width="12" height="16" rx="2"/><path d="M-2,-4 L0,2 L2,-4"/><line x1="0" y1="6" x2="0" y2="10"/>':i.includes("heiz")||i.includes("heat")||i.includes("warm")||i.includes("boiler")?'<path d="M-4,-10 C-4,-4 4,-4 4,-10"/><path d="M-4,-3 C-4,3 4,3 4,-3"/><path d="M-4,4 C-4,10 4,10 4,4"/>':i.includes("wash")||i.includes("spül")||i.includes("geschirr")||i.includes("wasch")?'<circle r="10" fill="none"/><circle r="5" fill="none"/><circle r="1.5" fill="currentColor" opacity="0.3" stroke="none"/>':i.includes("dryer")||i.includes("trockn")?'<circle r="10" fill="none"/><path d="M-4,-4 C0,-8 0,8 4,4" fill="none"/>':i.includes("pool")||i.includes("pump")?'<circle r="8" fill="none"/><path d="M-6,0 L6,0 M0,-6 L0,6" opacity="0.5"/><path d="M-4,-4 L4,4 M4,-4 L-4,4"/>':i.includes("klima")||i.includes("ac")||i.includes("cool")||i.includes("air")?'<rect x="-10" y="-6" width="20" height="12" rx="2"/><path d="M-6,6 C-6,10 -2,10 -2,6" fill="none"/><path d="M2,6 C2,10 6,10 6,6" fill="none"/>':i.includes("light")||i.includes("licht")||i.includes("lamp")?'<path d="M-5,-10 C-8,-2 -3,4 -2,6 L2,6 C3,4 8,-2 5,-10 C2,-14 -2,-14 -5,-10Z" fill="none"/><line x1="-2" y1="8" x2="2" y2="8"/>':i.includes("shelly")||i.includes("plug")||i.includes("switch")||i.includes("steckdose")?'<rect x="-8" y="-10" width="16" height="20" rx="3"/><circle cx="-3" cy="-2" r="2" fill="none"/><circle cx="3" cy="-2" r="2" fill="none"/><line x1="0" y1="4" x2="0" y2="7"/>':'<path d="M-3,-10 L-3,0 L-6,0 L0,10 L0,0 L3,0 L-3,-10Z" fill="none"/>'}getCardSize(){return 8}static getStubConfig(){return{entity_prefix:"sensor.sem_"}}},{type:"sem-system-diagram-card",name:"SEM System Diagram",description:"Responsive power flow visualization with circular nodes and shimmer animations"});let de=null;const he=dt||{solar:"#ff9800",gridImport:"#488fc2",gridExport:"#8353d1",batteryOut:"#4db6ac",home:"#5BC8D8",ev:"#8DC892"},pe={costs:{title:"energy_costs",y_label:"_currency_",stacked:!1,daily:[{suffix:"daily_costs",name:"Import",color:he.gridImport,type:"bar"},{suffix:"daily_export_revenue",name:"export",color:he.gridExport,type:"bar"},{suffix:"daily_net_cost",name:"net",color:he.solar,type:"line"}],monthly:[{suffix:"monthly_costs",name:"Import",color:he.gridImport,type:"bar"},{suffix:"monthly_export_revenue",name:"export",color:he.gridExport,type:"bar"},{suffix:"monthly_net_cost",name:"net",color:he.solar,type:"line"}]},savings:{title:"energy_savings",y_label:"_currency_",stacked:!0,daily:[{suffix:"daily_savings",name:"solar_savings",color:he.solar,type:"area"},{suffix:"daily_battery_savings",name:"battery_savings",color:he.batteryOut,type:"area"}],monthly:[{suffix:"monthly_savings",name:"solar_savings",color:he.solar,type:"area"},{suffix:"monthly_battery_savings",name:"battery_savings",color:he.batteryOut,type:"area"}]},energy:{title:"energy_balance",y_label:"kWh",stacked:!1,daily:[{suffix:"daily_solar_energy",name:"solar",color:he.solar,type:"bar"},{suffix:"daily_home_energy",name:"home",color:he.home,type:"bar"},{suffix:"daily_grid_import_energy",name:"grid_import",color:he.gridImport,type:"bar"},{suffix:"daily_grid_export_energy",name:"grid_export",color:he.gridExport,type:"bar"}],monthly:[{suffix:"monthly_solar_energy",name:"solar",color:he.solar,type:"bar"},{suffix:"monthly_home_energy",name:"home",color:he.home,type:"bar"},{suffix:"monthly_grid_import_energy",name:"grid_import",color:he.gridImport,type:"bar"},{suffix:"monthly_grid_export_energy",name:"grid_export",color:he.gridExport,type:"bar"}]},power:{title:"power_flow",y_label:"W",stacked:!1,hourly:[{suffix:"solar_power",name:"solar",color:he.solar,type:"area"},{suffix:"home_consumption_power",name:"home",color:he.home,type:"area"},{suffix:"grid_power",name:"grid",color:he.gridImport,type:"area"}]},battery:{title:"battery",y_label:"W",y2_label:"%",stacked:!1,hourly:[{suffix:"battery_power",name:"power",color:he.batteryOut,type:"area"},{suffix:"battery_soc",name:"soc",color:"#ff9800",type:"line",y_axis:1}]},ev:{title:"ev_charging",y_label:"W",stacked:!1,defaultPeriod:"24h",hourly:[{suffix:"ev_power",name:"ev_power",color:he.ev,type:"area"}],daily:[{suffix:"daily_ev_energy",name:"ev_energy",color:he.ev,type:"bar"}],monthly:[{suffix:"monthly_ev_energy",name:"ev_energy",color:he.ev,type:"bar"}]}};ft("sem-chart-card",class extends mt{constructor(){super(),this._chart=null,this._period=null,this._fetchTimer=null,this._cachedChartTheme=null,this._boundPeriodHandler=t=>this._onPeriodChange(t.detail),this._prefix="sensor.sem_",this._preset=null}setConfig(t){if(!t.preset&&!t.series)throw new Error("sem-chart-card requires either preset or series config");this._config=t,this._prefix=t.entity_prefix||"sensor.sem_",this._preset=t.preset?pe[t.preset]:null,this.requestUpdate()}set hass(t){this._hass,this._hass=t;const e=t?.language;if(e!==this._lang)return this._lang=e,void this.requestUpdate();this._period||this._setDefaultPeriod()}get hass(){return this._hass}connectedCallback(){super.connectedCallback(),document.addEventListener("sem-period-change",this._boundPeriodHandler)}disconnectedCallback(){super.disconnectedCallback(),document.removeEventListener("sem-period-change",this._boundPeriodHandler),this._chart&&(this._chart.destroy(),this._chart=null),clearTimeout(this._fetchTimer)}firstUpdated(){this._period||this._setDefaultPeriod()}static get styles(){return a`
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
        `}render(){const t=this._preset||{},e=this._config?.title||this._t(t.title||"SEM Chart");return H`
            <ha-card>
                <div class="sem-chart-wrap">
                    <div class="chart-header">
                        <div class="chart-title">${e}</div>
                        <div class="chart-subtitle"></div>
                    </div>
                    <div class="chart-container">
                        <canvas></canvas>
                        <div class="empty-msg">Loading\u2026</div>
                    </div>
                </div>
            </ha-card>
        `}_setDefaultPeriod(){const t=new Date,e=this._preset;if(e&&("24h"===e.defaultPeriod||e.hourly&&!e.daily)){const e=new Date(t.getTime()-864e5);this._onPeriodChange({start:e,end:t,granularity:"hour",label:"Last 24h",key:"24h"})}else{const e=t.getDay()||7,i=new Date(t.getFullYear(),t.getMonth(),t.getDate());i.setDate(i.getDate()-(e-1)),this._onPeriodChange({start:i,end:t,granularity:"day",label:"This Week",key:"week"})}}_onPeriodChange(t){this._period=t;const e=this.renderRoot?.querySelector(".chart-subtitle");e&&(e.textContent=t.label||""),clearTimeout(this._fetchTimer),this._fetchTimer=setTimeout(()=>this._fetchAndRender(),150)}_resolveSeries(){if(this._config?.series)return this._config.series.map(t=>({entity:t.entity,name:t.name||t.entity,color:t.color||"#42A5F5",type:t.type||"bar",y_axis:t.y_axis||0}));const t=this._preset;if(!t)return[];const e=this._period?.granularity||"day";return("hour"===e&&t.hourly?t.hourly:"month"===e&&t.monthly?t.monthly:t.daily||t.hourly||[]).map(t=>({entity:`${this._prefix}${t.suffix}`,name:this._t(t.name),color:t.color,type:t.type,y_axis:t.y_axis||0}))}async _fetchAndRender(){if(!this._hass||!this._period)return;const t=this._resolveSeries();if(!t.length)return;const{start:e,end:i,granularity:s}=this._period;let r;try{r=await this._fetchStatistics(t,e.toISOString(),i.toISOString(),s)}catch(t){return console.debug("sem-chart-card: fetch error",t),void this._showEmpty(this._t("data_unavailable"))}r&&!r.every(t=>!t.data.length)?(this._hideEmpty(),await this._renderChart(r,t)):this._showEmpty(this._t("no_data_for_period"))}async _fetchStatistics(t,e,i,s){const r=t.map(t=>t.entity),a="month"===s?"month":"hour"===s?"hour":"day";let o;try{o=await this._hass.callWS({type:"recorder/statistics_during_period",start_time:e,end_time:i,statistic_ids:r,period:a,types:["state","mean","max"]})}catch{o=await this._hass.callWS({type:"history/statistics_during_period",start_time:e,end_time:i,statistic_ids:r,period:a})}return t.map(t=>({data:(o[t.entity]||[]).map(t=>({x:new Date(t.start),y:t.max??t.state??t.mean??0}))}))}async _renderChart(t,e){const i=await(de||(de=new Promise((t,e)=>{if(window.Chart)return void t(window.Chart);const i=document.createElement("script");i.src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js",i.onload=()=>{const e=document.createElement("script");e.src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js",e.onload=()=>t(window.Chart),e.onerror=()=>t(window.Chart),document.head.appendChild(e)},i.onerror=()=>e(new Error("Failed to load Chart.js")),document.head.appendChild(i)}),de)),s=this.renderRoot.querySelector("canvas");if(!s)return;const r=this._theme(),a=this._preset||{},o=this._config?.stacked??a.stacked??!1;let n=this._config?.y_label||a.y_label||"";"_currency_"===n&&(n=_t(this._hass));const l=a.y2_label||"",c=e.some(t=>1===t.y_axis),d=this._period?.granularity||"day",h=s.getContext("2d"),p=e.map((e,i)=>{const s="area"===e.type,r="bar"===e.type;return{label:e.name,data:t[i].data,backgroundColor:r?e.color+"CC":s?e.color+"30":"transparent",borderColor:e.color,borderWidth:r?0:2,fill:!!s&&"origin",type:r?"bar":"line",tension:.4,pointRadius:0,pointHitRadius:10,pointHoverRadius:4,pointHoverBorderWidth:2,pointHoverBackgroundColor:e.color,pointHoverBorderColor:"#fff",yAxisID:1===e.y_axis?"y1":"y",order:r?2:1,borderRadius:r?4:0,barPercentage:.7}}),g="hour"===d?"hour":"month"===d?"month":"day",_={id:"crosshair",afterDraw(t){if(t.tooltip?._active?.length){const e=t.tooltip._active[0].element.x,i=t.scales.y,s=t.ctx;s.save(),s.beginPath(),s.moveTo(e,i.top),s.lineTo(e,i.bottom),s.lineWidth=1,s.strokeStyle="rgba(255,255,255,0.15)",s.stroke(),s.restore()}}},u={type:"bar",data:{datasets:p},plugins:[_,{id:"gradientFill",beforeDatasetsDraw(t){const i=t.ctx;t.data.datasets.forEach((s,r)=>{if("area"!==e[r]?.type)return;if(t.getDatasetMeta(r).hidden)return;const a=t.scales[s.yAxisID||"y"];if(!a)return;const o=i.createLinearGradient(0,a.top,0,a.bottom);o.addColorStop(0,s.borderColor+"60"),o.addColorStop(.6,s.borderColor+"18"),o.addColorStop(1,s.borderColor+"02"),s.backgroundColor=o})}}],options:{responsive:!0,maintainAspectRatio:!1,animation:{duration:300,easing:"easeOutQuart"},interaction:{mode:"index",intersect:!1},plugins:{legend:{display:!0,position:"bottom",labels:{color:r.textSec||"#9e9e9e",font:{size:11,weight:"500",family:"'Segoe UI','Roboto',sans-serif"},boxWidth:12,boxHeight:12,borderRadius:3,useBorderRadius:!0,padding:14,generateLabels:t=>i.defaults.plugins.legend.labels.generateLabels(t).map((e,i)=>{const s=t.data.datasets[i],r=s.data[s.data.length-1],a=r?.y??0,o="y1"===s.yAxisID?"%":n||"",l=Math.abs(a),c=l>=1e3?(a/1e3).toFixed(1)+"k":l<10?a.toFixed(1):a.toFixed(0);return e.text=`${e.text}: ${c} ${o}`,e})}},tooltip:{backgroundColor:r.tooltipBg||"rgba(15,18,25,0.94)",titleColor:r.tooltipText||"#e0e0e0",titleFont:{family:"'Segoe UI','Roboto',sans-serif",weight:"600",size:12},bodyColor:r.textSec||"#b0b0b0",bodyFont:{family:"'Segoe UI','Roboto',sans-serif",size:11},borderColor:r.tooltipBorder||"rgba(255,255,255,0.08)",borderWidth:1,cornerRadius:10,padding:{top:10,bottom:10,left:14,right:14},bodySpacing:6,displayColors:!0,boxPadding:4,callbacks:{label:t=>{const e=t.parsed.y,i="y1"===t.dataset.yAxisID?"%":n,s=Math.abs(e),r=s>=1e3?(e/1e3).toFixed(1)+"k":s<10?e.toFixed(2):e.toFixed(1);return` ${t.dataset.label}: ${r} ${i}`}}}},scales:{x:{type:"time",min:this._period.start.toISOString(),max:this._period.end.toISOString(),time:{unit:g,tooltipFormat:"hour"===d?"HH:mm":"month"===d?"MMM yyyy":"dd MMM",displayFormats:{hour:"HH:mm",day:"dd MMM",month:"MMM"}},grid:{color:"rgba(255,255,255,0.02)",drawBorder:!1,drawTicks:!1},ticks:{color:r.textSec||"#757575",font:{size:10,family:"'Segoe UI','Roboto',sans-serif"},maxRotation:0,padding:6},stacked:o},y:{position:"left",grid:{color:"rgba(255,255,255,0.04)",drawBorder:!1,drawTicks:!1},ticks:{color:r.textSec||"#757575",font:{size:10,family:"'Segoe UI','Roboto',sans-serif"},padding:8,callback:t=>{const e=Math.abs(t);return e>=1e3?(t/1e3).toFixed(1)+"k":e<.01&&e>0?"":t%1==0?t:t.toFixed(1)}},title:{display:!!n,text:n,color:r.textSec||"#757575",font:{size:11,family:"'Segoe UI','Roboto',sans-serif"}},stacked:o,beginAtZero:"W"!==n}}}};c&&(u.options.scales.y1={position:"right",grid:{drawOnChartArea:!1,drawTicks:!1},ticks:{color:"#ff9800",font:{size:10},padding:8,callback:t=>t+"%"},title:{display:!!l,text:l,color:"#ff9800",font:{size:11}},min:0,max:100}),this._chart&&(this._chart.destroy(),this._chart=null),this._chart=new i(h,u)}_showEmpty(t){const e=this.renderRoot.querySelector(".empty-msg");e&&(e.textContent=t,e.classList.add("visible"));const i=this.renderRoot.querySelector("canvas");i&&(i.style.display="none")}_hideEmpty(){const t=this.renderRoot.querySelector(".empty-msg");t&&t.classList.remove("visible");const e=this.renderRoot.querySelector("canvas");e&&(e.style.display="block")}getCardSize(){return 5}static getStubConfig(){return{preset:"costs"}}},{type:"sem-chart-card",name:"SEM Chart",description:"Period-reactive chart with glassmorphism styling and built-in presets"}),function(){window.Sortable||function(t,e){"object"==typeof exports&&"undefined"!=typeof module?module.exports=e():"function"==typeof define&&define.amd?define(e):(t=t||self).Sortable=e()}(this,function(){function t(t,e){var i,s=Object.keys(t);return Object.getOwnPropertySymbols&&(i=Object.getOwnPropertySymbols(t),e&&(i=i.filter(function(e){return Object.getOwnPropertyDescriptor(t,e).enumerable})),s.push.apply(s,i)),s}function e(e){for(var i=1;i<arguments.length;i++){var s=null!=arguments[i]?arguments[i]:{};i%2?t(Object(s),!0).forEach(function(t){var i,r;i=e,t=s[r=t],r in i?Object.defineProperty(i,r,{value:t,enumerable:!0,configurable:!0,writable:!0}):i[r]=t}):Object.getOwnPropertyDescriptors?Object.defineProperties(e,Object.getOwnPropertyDescriptors(s)):t(Object(s)).forEach(function(t){Object.defineProperty(e,t,Object.getOwnPropertyDescriptor(s,t))})}return e}function i(t){return(i="function"==typeof Symbol&&"symbol"==typeof Symbol.iterator?function(t){return typeof t}:function(t){return t&&"function"==typeof Symbol&&t.constructor===Symbol&&t!==Symbol.prototype?"symbol":typeof t})(t)}function s(){return(s=Object.assign||function(t){for(var e=1;e<arguments.length;e++){var i,s=arguments[e];for(i in s)Object.prototype.hasOwnProperty.call(s,i)&&(t[i]=s[i])}return t}).apply(this,arguments)}function r(t){return function(t){if(Array.isArray(t))return a(t)}(t)||function(t){if("undefined"!=typeof Symbol&&null!=t[Symbol.iterator]||null!=t["@@iterator"])return Array.from(t)}(t)||function(t,e){if(t){if("string"==typeof t)return a(t,e);var i=Object.prototype.toString.call(t).slice(8,-1);return"Map"===(i="Object"===i&&t.constructor?t.constructor.name:i)||"Set"===i?Array.from(t):"Arguments"===i||/^(?:Ui|I)nt(?:8|16|32)(?:Clamped)?Array$/.test(i)?a(t,e):void 0}}(t)||function(){throw new TypeError("Invalid attempt to spread non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method.")}()}function a(t,e){(null==e||e>t.length)&&(e=t.length);for(var i=0,s=new Array(e);i<e;i++)s[i]=t[i];return s}function o(t){if("undefined"!=typeof window&&window.navigator)return!!navigator.userAgent.match(t)}var n=o(/(?:Trident.*rv[ :]?11\.|msie|iemobile|Windows Phone)/i),l=o(/Edge/i),c=o(/firefox/i),d=o(/safari/i)&&!o(/chrome/i)&&!o(/android/i),h=o(/iP(ad|od|hone)/i),p=o(/chrome/i)&&o(/android/i),g={capture:!1,passive:!1};function _(t,e,i){t.addEventListener(e,i,!n&&g)}function u(t,e,i){t.removeEventListener(e,i,!n&&g)}function f(t,e){if(e&&(">"===e[0]&&(e=e.substring(1)),t))try{if(t.matches)return t.matches(e);if(t.msMatchesSelector)return t.msMatchesSelector(e);if(t.webkitMatchesSelector)return t.webkitMatchesSelector(e)}catch(t){return}}function m(t){return t.host&&t!==document&&t.host.nodeType?t.host:t.parentNode}function v(t,e,i,s){if(t){i=i||document;do{if(null!=e&&(">"!==e[0]||t.parentNode===i)&&f(t,e)||s&&t===i)return t}while(t!==i&&(t=m(t)))}return null}var y,x=/\s+/g;function b(t,e,i){var s;t&&e&&(t.classList?t.classList[i?"add":"remove"](e):(s=(" "+t.className+" ").replace(x," ").replace(" "+e+" "," "),t.className=(s+(i?" "+e:"")).replace(x," ")))}function $(t,e,i){var s=t&&t.style;if(s){if(void 0===i)return document.defaultView&&document.defaultView.getComputedStyle?i=document.defaultView.getComputedStyle(t,""):t.currentStyle&&(i=t.currentStyle),void 0===e?i:i[e];s[e=e in s||-1!==e.indexOf("webkit")?e:"-webkit-"+e]=i+("string"==typeof i?"":"px")}}function w(t,e){var i="";if("string"==typeof t)i=t;else do{var s=$(t,"transform")}while(s&&"none"!==s&&(i=s+" "+i),!e&&(t=t.parentNode));var r=window.DOMMatrix||window.WebKitCSSMatrix||window.CSSMatrix||window.MSCSSMatrix;return r&&new r(i)}function k(t,e,i){if(t){var s=t.getElementsByTagName(e),r=0,a=s.length;if(i)for(;r<a;r++)i(s[r],r);return s}return[]}function S(){return document.scrollingElement||document.documentElement}function C(t,e,i,s,r){if(t.getBoundingClientRect||t===window){var a,o,l,c,d,h,p=t!==window&&t.parentNode&&t!==S()?(o=(a=t.getBoundingClientRect()).top,l=a.left,c=a.bottom,d=a.right,h=a.height,a.width):(l=o=0,c=window.innerHeight,d=window.innerWidth,h=window.innerHeight,window.innerWidth);if((e||i)&&t!==window&&(r=r||t.parentNode,!n))do{if(r&&r.getBoundingClientRect&&("none"!==$(r,"transform")||i&&"static"!==$(r,"position"))){var g=r.getBoundingClientRect();o-=g.top+parseInt($(r,"border-top-width")),l-=g.left+parseInt($(r,"border-left-width")),c=o+a.height,d=l+a.width;break}}while(r=r.parentNode);return s&&t!==window&&(s=(e=w(r||t))&&e.a,t=e&&e.d,e&&(c=(o/=t)+(h/=t),d=(l/=s)+(p/=s))),{top:o,left:l,bottom:c,right:d,width:p,height:h}}}function E(t,e,i){for(var s=T(t,!0),r=C(t)[e];s;){if(!(C(s)[i]<=r))return s;if(s===S())break;s=T(s,!1)}return!1}function z(t,e,i,s){for(var r=0,a=0,o=t.children;a<o.length;){if("none"!==o[a].style.display&&o[a]!==Pt.ghost&&(s||o[a]!==Pt.dragged)&&v(o[a],i.draggable,t,!1)){if(r===e)return o[a];r++}a++}return null}function M(t,e){for(var i=t.lastElementChild;i&&(i===Pt.ghost||"none"===$(i,"display")||e&&!f(i,e));)i=i.previousElementSibling;return i||null}function D(t,e){var i=0;if(!t||!t.parentNode)return-1;for(;t=t.previousElementSibling;)"TEMPLATE"===t.nodeName.toUpperCase()||t===Pt.clone||e&&!f(t,e)||i++;return i}function F(t){var e=0,i=0,s=S();if(t)do{var r=(a=w(t)).a,a=a.d}while(e+=t.scrollLeft*r,i+=t.scrollTop*a,t!==s&&(t=t.parentNode));return[e,i]}function T(t,e){if(!t||!t.getBoundingClientRect)return S();var i=t,s=!1;do{if(i.clientWidth<i.scrollWidth||i.clientHeight<i.scrollHeight){var r=$(i);if(i.clientWidth<i.scrollWidth&&("auto"==r.overflowX||"scroll"==r.overflowX)||i.clientHeight<i.scrollHeight&&("auto"==r.overflowY||"scroll"==r.overflowY)){if(!i.getBoundingClientRect||i===document.body)return S();if(s||e)return i;s=!0}}}while(i=i.parentNode);return S()}function A(t,e){return Math.round(t.top)===Math.round(e.top)&&Math.round(t.left)===Math.round(e.left)&&Math.round(t.height)===Math.round(e.height)&&Math.round(t.width)===Math.round(e.width)}function I(t,e){return function(){var i;y||(1===(i=arguments).length?t.call(this,i[0]):t.apply(this,i),y=setTimeout(function(){y=void 0},e))}}function R(t,e,i){t.scrollLeft+=e,t.scrollTop+=i}function N(t){var e=window.Polymer,i=window.jQuery||window.Zepto;return e&&e.dom?e.dom(t).cloneNode(!0):i?i(t).clone(!0)[0]:t.cloneNode(!0)}function O(t,e){$(t,"position","absolute"),$(t,"top",e.top),$(t,"left",e.left),$(t,"width",e.width),$(t,"height",e.height)}function P(t){$(t,"position",""),$(t,"top",""),$(t,"left",""),$(t,"width",""),$(t,"height","")}function B(t,e,i){var s={};return Array.from(t.children).forEach(function(r){var a;v(r,e.draggable,t,!1)&&!r.animated&&r!==i&&(a=C(r),s.left=Math.min(null!==(r=s.left)&&void 0!==r?r:1/0,a.left),s.top=Math.min(null!==(r=s.top)&&void 0!==r?r:1/0,a.top),s.right=Math.max(null!==(r=s.right)&&void 0!==r?r:-1/0,a.right),s.bottom=Math.max(null!==(r=s.bottom)&&void 0!==r?r:-1/0,a.bottom))}),s.width=s.right-s.left,s.height=s.bottom-s.top,s.x=s.left,s.y=s.top,s}var L="Sortable"+(new Date).getTime();var U=[],W={initializeByDefault:!0},H={mount:function(t){for(var e in W)!W.hasOwnProperty(e)||e in t||(t[e]=W[e]);U.forEach(function(e){if(e.pluginName===t.pluginName)throw"Sortable: Cannot mount plugin ".concat(t.pluginName," more than once")}),U.push(t)},pluginEvent:function(t,i,s){var r=this;this.eventCanceled=!1,s.cancel=function(){r.eventCanceled=!0};var a=t+"Global";U.forEach(function(r){i[r.pluginName]&&(i[r.pluginName][a]&&i[r.pluginName][a](e({sortable:i},s)),i.options[r.pluginName]&&i[r.pluginName][t]&&i[r.pluginName][t](e({sortable:i},s)))})},initializePlugins:function(t,e,i,r){for(var a in U.forEach(function(r){var a=r.pluginName;(t.options[a]||r.initializeByDefault)&&((r=new r(t,e,t.options)).sortable=t,r.options=t.options,t[a]=r,s(i,r.defaults))}),t.options){var o;t.options.hasOwnProperty(a)&&void 0!==(o=this.modifyOption(t,a,t.options[a]))&&(t.options[a]=o)}},getEventProperties:function(t,e){var i={};return U.forEach(function(r){"function"==typeof r.eventProperties&&s(i,r.eventProperties.call(e[r.pluginName],t))}),i},modifyOption:function(t,e,i){var s;return U.forEach(function(r){t[r.pluginName]&&r.optionListeners&&"function"==typeof r.optionListeners[e]&&(s=r.optionListeners[e].call(t[r.pluginName],i))}),s}};function j(t){var i=t.sortable,s=t.rootEl,r=t.name,a=t.targetEl,o=t.cloneEl,c=t.toEl,d=t.fromEl,h=t.oldIndex,p=t.newIndex,g=t.oldDraggableIndex,_=t.newDraggableIndex,u=t.originalEvent,f=t.putSortable,m=t.extraEventProperties;if(i=i||s&&s[L]){var v,y=i.options;t="on"+r.charAt(0).toUpperCase()+r.substr(1);!window.CustomEvent||n||l?(v=document.createEvent("Event")).initEvent(r,!0,!0):v=new CustomEvent(r,{bubbles:!0,cancelable:!0}),v.to=c||s,v.from=d||s,v.item=a||s,v.clone=o,v.oldIndex=h,v.newIndex=p,v.oldDraggableIndex=g,v.newDraggableIndex=_,v.originalEvent=u,v.pullMode=f?f.lastPutMode:void 0;var x,b=e(e({},m),H.getEventProperties(r,i));for(x in b)v[x]=b[x];s&&s.dispatchEvent(v),y[t]&&y[t].call(i,v)}}function G(t,i){var s=(r=2<arguments.length&&void 0!==arguments[2]?arguments[2]:{}).evt,r=function(t,e){if(null==t)return{};var i,s=function(t,e){if(null==t)return{};for(var i,s={},r=Object.keys(t),a=0;a<r.length;a++)i=r[a],0<=e.indexOf(i)||(s[i]=t[i]);return s}(t,e);if(Object.getOwnPropertySymbols)for(var r=Object.getOwnPropertySymbols(t),a=0;a<r.length;a++)i=r[a],0<=e.indexOf(i)||Object.prototype.propertyIsEnumerable.call(t,i)&&(s[i]=t[i]);return s}(r,K);H.pluginEvent.bind(Pt)(t,i,e({dragEl:V,parentEl:Y,ghostEl:X,rootEl:Z,nextEl:J,lastDownEl:Q,cloneEl:tt,cloneHidden:et,dragStarted:_t,putSortable:nt,activeSortable:Pt.active,originalEvent:s,oldIndex:it,oldDraggableIndex:rt,newIndex:st,newDraggableIndex:at,hideGhostForTarget:It,unhideGhostForTarget:Rt,cloneNowHidden:function(){et=!0},cloneNowShown:function(){et=!1},dispatchSortableEvent:function(t){q({sortable:i,name:t,originalEvent:s})}},r))}var K=["evt"];function q(t){j(e({putSortable:nt,cloneEl:tt,targetEl:V,rootEl:Z,oldIndex:it,oldDraggableIndex:rt,newIndex:st,newDraggableIndex:at},t))}var V,Y,X,Z,J,Q,tt,et,it,st,rt,at,ot,nt,lt,ct,dt,ht,pt,gt,_t,ut,ft,mt,vt,yt=!1,xt=!1,bt=[],$t=!1,wt=!1,kt=[],St=!1,Ct=[],Et="undefined"!=typeof document,zt=h,Mt=l||n?"cssFloat":"float",Dt=Et&&!p&&!h&&"draggable"in document.createElement("div"),Ft=function(){if(Et){if(n)return!1;var t=document.createElement("x");return t.style.cssText="pointer-events:auto","auto"===t.style.pointerEvents}}(),Tt=function(t,e){var i=$(t),s=parseInt(i.width)-parseInt(i.paddingLeft)-parseInt(i.paddingRight)-parseInt(i.borderLeftWidth)-parseInt(i.borderRightWidth),r=z(t,0,e),a=z(t,1,e),o=r&&$(r),n=a&&$(a),l=o&&parseInt(o.marginLeft)+parseInt(o.marginRight)+C(r).width;t=n&&parseInt(n.marginLeft)+parseInt(n.marginRight)+C(a).width;return"flex"===i.display?"column"===i.flexDirection||"column-reverse"===i.flexDirection?"vertical":"horizontal":"grid"===i.display?i.gridTemplateColumns.split(" ").length<=1?"vertical":"horizontal":r&&o.float&&"none"!==o.float?(e="left"===o.float?"left":"right",!a||"both"!==n.clear&&n.clear!==e?"horizontal":"vertical"):r&&("block"===o.display||"flex"===o.display||"table"===o.display||"grid"===o.display||s<=l&&"none"===i[Mt]||a&&"none"===i[Mt]&&s<l+t)?"vertical":"horizontal"},At=function(t){function e(t,i){return function(s,r,a,o){var n=s.options.group.name&&r.options.group.name&&s.options.group.name===r.options.group.name;return!(null!=t||!i&&!n)||null!=t&&!1!==t&&(i&&"clone"===t?t:"function"==typeof t?e(t(s,r,a,o),i)(s,r,a,o):(r=(i?s:r).options.group.name,!0===t||"string"==typeof t&&t===r||t.join&&-1<t.indexOf(r)))}}var s={},r=t.group;r&&"object"==i(r)||(r={name:r}),s.name=r.name,s.checkPull=e(r.pull,!0),s.checkPut=e(r.put),s.revertClone=r.revertClone,t.group=s},It=function(){!Ft&&X&&$(X,"display","none")},Rt=function(){!Ft&&X&&$(X,"display","")};function Nt(t){if(V){t=t.touches?t.touches[0]:t;var e=(r=t.clientX,a=t.clientY,bt.some(function(t){if((s=t[L].options.emptyInsertThreshold)&&!M(t)){var e=C(t),i=r>=e.left-s&&r<=e.right+s,s=a>=e.top-s&&a<=e.bottom+s;return i&&s?o=t:void 0}}),o);if(e){var i,s={};for(i in t)t.hasOwnProperty(i)&&(s[i]=t[i]);s.target=s.rootEl=e,s.preventDefault=void 0,s.stopPropagation=void 0,e[L]._onDragOver(s)}}var r,a,o}function Ot(t){V&&V.parentNode[L]._isOutsideThisEl(t.target)}function Pt(t,i){if(!t||!t.nodeType||1!==t.nodeType)throw"Sortable: `el` must be an HTMLElement, not ".concat({}.toString.call(t));this.el=t,this.options=i=s({},i),t[L]=this;var r,a,o={group:null,sort:!0,disabled:!1,store:null,handle:null,draggable:/^[uo]l$/i.test(t.nodeName)?">li":">*",swapThreshold:1,invertSwap:!1,invertedSwapThreshold:null,removeCloneOnHide:!0,direction:function(){return Tt(t,this.options)},ghostClass:"sortable-ghost",chosenClass:"sortable-chosen",dragClass:"sortable-drag",ignore:"a, img",filter:null,preventOnFilter:!0,animation:0,easing:null,setData:function(t,e){t.setData("Text",e.textContent)},dropBubble:!1,dragoverBubble:!1,dataIdAttr:"data-id",delay:0,delayOnTouchOnly:!1,touchStartThreshold:(Number.parseInt?Number:window).parseInt(window.devicePixelRatio,10)||1,forceFallback:!1,fallbackClass:"sortable-fallback",fallbackOnBody:!1,fallbackTolerance:0,fallbackOffset:{x:0,y:0},supportPointer:!1!==Pt.supportPointer&&"PointerEvent"in window&&(!d||h),emptyInsertThreshold:5};for(r in H.initializePlugins(this,t,o),o)r in i||(i[r]=o[r]);for(a in At(i),this)"_"===a.charAt(0)&&"function"==typeof this[a]&&(this[a]=this[a].bind(this));this.nativeDraggable=!i.forceFallback&&Dt,this.nativeDraggable&&(this.options.touchStartThreshold=1),i.supportPointer?_(t,"pointerdown",this._onTapStart):(_(t,"mousedown",this._onTapStart),_(t,"touchstart",this._onTapStart)),this.nativeDraggable&&(_(t,"dragover",this),_(t,"dragenter",this)),bt.push(this.el),i.store&&i.store.get&&this.sort(i.store.get(this)||[]),s(this,function(){var t,i=[];return{captureAnimationState:function(){i=[],this.options.animation&&[].slice.call(this.el.children).forEach(function(t){var s,r;"none"!==$(t,"display")&&t!==Pt.ghost&&(i.push({target:t,rect:C(t)}),s=e({},i[i.length-1].rect),!t.thisAnimationDuration||(r=w(t,!0))&&(s.top-=r.f,s.left-=r.e),t.fromRect=s)})},addAnimationState:function(t){i.push(t)},removeAnimationState:function(t){i.splice(function(t,e){for(var i in t)if(t.hasOwnProperty(i))for(var s in e)if(e.hasOwnProperty(s)&&e[s]===t[i][s])return Number(i);return-1}(i,{target:t}),1)},animateAll:function(e){var s=this;if(!this.options.animation)return clearTimeout(t),void("function"==typeof e&&e());var r=!1,a=0;i.forEach(function(t){var e=0,i=t.target,o=i.fromRect,n=C(i),l=i.prevFromRect,c=i.prevToRect,d=t.rect,h=w(i,!0);h&&(n.top-=h.f,n.left-=h.e),i.toRect=n,i.thisAnimationDuration&&A(l,n)&&!A(o,n)&&(d.top-n.top)/(d.left-n.left)==(o.top-n.top)/(o.left-n.left)&&(t=d,h=l,l=c,c=s.options,e=Math.sqrt(Math.pow(h.top-t.top,2)+Math.pow(h.left-t.left,2))/Math.sqrt(Math.pow(h.top-l.top,2)+Math.pow(h.left-l.left,2))*c.animation),A(n,o)||(i.prevFromRect=o,i.prevToRect=n,e=e||s.options.animation,s.animate(i,d,n,e)),e&&(r=!0,a=Math.max(a,e),clearTimeout(i.animationResetTimer),i.animationResetTimer=setTimeout(function(){i.animationTime=0,i.prevFromRect=null,i.fromRect=null,i.prevToRect=null,i.thisAnimationDuration=null},e),i.thisAnimationDuration=e)}),clearTimeout(t),r?t=setTimeout(function(){"function"==typeof e&&e()},a):"function"==typeof e&&e(),i=[]},animate:function(t,e,i,s){var r,a;s&&($(t,"transition",""),$(t,"transform",""),r=(a=w(this.el))&&a.a,a=a&&a.d,r=(e.left-i.left)/(r||1),a=(e.top-i.top)/(a||1),t.animatingX=!!r,t.animatingY=!!a,$(t,"transform","translate3d("+r+"px,"+a+"px,0)"),this.forRepaintDummy=t.offsetWidth,$(t,"transition","transform "+s+"ms"+(this.options.easing?" "+this.options.easing:"")),$(t,"transform","translate3d(0,0,0)"),"number"==typeof t.animated&&clearTimeout(t.animated),t.animated=setTimeout(function(){$(t,"transition",""),$(t,"transform",""),t.animated=!1,t.animatingX=!1,t.animatingY=!1},s))}}}())}function Bt(t,e,i,s,r,a,o,c){var d,h,p=t[L],g=p.options.onMove;return!window.CustomEvent||n||l?(d=document.createEvent("Event")).initEvent("move",!0,!0):d=new CustomEvent("move",{bubbles:!0,cancelable:!0}),d.to=e,d.from=t,d.dragged=i,d.draggedRect=s,d.related=r||e,d.relatedRect=a||C(e),d.willInsertAfter=c,d.originalEvent=o,t.dispatchEvent(d),g?g.call(p,d,o):h}function Lt(t){t.draggable=!1}function Ut(){St=!1}function Wt(t){return setTimeout(t,0)}function Ht(t){return clearTimeout(t)}Et&&!p&&document.addEventListener("click",function(t){if(xt)return t.preventDefault(),t.stopPropagation&&t.stopPropagation(),t.stopImmediatePropagation&&t.stopImmediatePropagation(),xt=!1},!0),Pt.prototype={constructor:Pt,_isOutsideThisEl:function(t){this.el.contains(t)||t===this.el||(ut=null)},_getDirection:function(t,e){return"function"==typeof this.options.direction?this.options.direction.call(this,t,e,V):this.options.direction},_onTapStart:function(t){if(t.cancelable){var e=this,i=this.el,s=this.options,r=s.preventOnFilter,a=t.type,o=t.touches&&t.touches[0]||t.pointerType&&"touch"===t.pointerType&&t,n=(o||t).target,l=t.target.shadowRoot&&(t.path&&t.path[0]||t.composedPath&&t.composedPath()[0])||n,c=s.filter;if(function(t){Ct.length=0;for(var e=t.getElementsByTagName("input"),i=e.length;i--;){var s=e[i];s.checked&&Ct.push(s)}}(i),!V&&!(/mousedown|pointerdown/.test(a)&&0!==t.button||s.disabled)&&!l.isContentEditable&&(this.nativeDraggable||!d||!n||"SELECT"!==n.tagName.toUpperCase())&&!((n=v(n,s.draggable,i,!1))&&n.animated||Q===n)){if(it=D(n),rt=D(n,s.draggable),"function"==typeof c){if(c.call(this,t,n,this))return q({sortable:e,rootEl:l,name:"filter",targetEl:n,toEl:i,fromEl:i}),G("filter",e,{evt:t}),void(r&&t.preventDefault())}else if(c=c&&c.split(",").some(function(s){if(s=v(l,s.trim(),i,!1))return q({sortable:e,rootEl:s,name:"filter",targetEl:n,fromEl:i,toEl:i}),G("filter",e,{evt:t}),!0}))return void(r&&t.preventDefault());s.handle&&!v(l,s.handle,i,!1)||this._prepareDragStart(t,o,n)}}},_prepareDragStart:function(t,e,i){var s,r=this,a=r.el,o=r.options,d=a.ownerDocument;i&&!V&&i.parentNode===a&&(s=C(i),Z=a,Y=(V=i).parentNode,J=V.nextSibling,Q=i,ot=o.group,lt={target:Pt.dragged=V,clientX:(e||t).clientX,clientY:(e||t).clientY},pt=lt.clientX-s.left,gt=lt.clientY-s.top,this._lastX=(e||t).clientX,this._lastY=(e||t).clientY,V.style["will-change"]="all",s=function(){G("delayEnded",r,{evt:t}),Pt.eventCanceled?r._onDrop():(r._disableDelayedDragEvents(),!c&&r.nativeDraggable&&(V.draggable=!0),r._triggerDragStart(t,e),q({sortable:r,name:"choose",originalEvent:t}),b(V,o.chosenClass,!0))},o.ignore.split(",").forEach(function(t){k(V,t.trim(),Lt)}),_(d,"dragover",Nt),_(d,"mousemove",Nt),_(d,"touchmove",Nt),o.supportPointer?(_(d,"pointerup",r._onDrop),this.nativeDraggable||_(d,"pointercancel",r._onDrop)):(_(d,"mouseup",r._onDrop),_(d,"touchend",r._onDrop),_(d,"touchcancel",r._onDrop)),c&&this.nativeDraggable&&(this.options.touchStartThreshold=4,V.draggable=!0),G("delayStart",this,{evt:t}),!o.delay||o.delayOnTouchOnly&&!e||this.nativeDraggable&&(l||n)?s():Pt.eventCanceled?this._onDrop():(o.supportPointer?(_(d,"pointerup",r._disableDelayedDrag),_(d,"pointercancel",r._disableDelayedDrag)):(_(d,"mouseup",r._disableDelayedDrag),_(d,"touchend",r._disableDelayedDrag),_(d,"touchcancel",r._disableDelayedDrag)),_(d,"mousemove",r._delayedDragTouchMoveHandler),_(d,"touchmove",r._delayedDragTouchMoveHandler),o.supportPointer&&_(d,"pointermove",r._delayedDragTouchMoveHandler),r._dragStartTimer=setTimeout(s,o.delay)))},_delayedDragTouchMoveHandler:function(t){t=t.touches?t.touches[0]:t,Math.max(Math.abs(t.clientX-this._lastX),Math.abs(t.clientY-this._lastY))>=Math.floor(this.options.touchStartThreshold/(this.nativeDraggable&&window.devicePixelRatio||1))&&this._disableDelayedDrag()},_disableDelayedDrag:function(){V&&Lt(V),clearTimeout(this._dragStartTimer),this._disableDelayedDragEvents()},_disableDelayedDragEvents:function(){var t=this.el.ownerDocument;u(t,"mouseup",this._disableDelayedDrag),u(t,"touchend",this._disableDelayedDrag),u(t,"touchcancel",this._disableDelayedDrag),u(t,"pointerup",this._disableDelayedDrag),u(t,"pointercancel",this._disableDelayedDrag),u(t,"mousemove",this._delayedDragTouchMoveHandler),u(t,"touchmove",this._delayedDragTouchMoveHandler),u(t,"pointermove",this._delayedDragTouchMoveHandler)},_triggerDragStart:function(t,e){e=e||"touch"==t.pointerType&&t,!this.nativeDraggable||e?this.options.supportPointer?_(document,"pointermove",this._onTouchMove):_(document,e?"touchmove":"mousemove",this._onTouchMove):(_(V,"dragend",this),_(Z,"dragstart",this._onDragStart));try{document.selection?Wt(function(){document.selection.empty()}):window.getSelection().removeAllRanges()}catch(t){}},_dragStarted:function(t,e){var i;yt=!1,Z&&V?(G("dragStarted",this,{evt:e}),this.nativeDraggable&&_(document,"dragover",Ot),i=this.options,t||b(V,i.dragClass,!1),b(V,i.ghostClass,!0),Pt.active=this,t&&this._appendGhost(),q({sortable:this,name:"start",originalEvent:e})):this._nulling()},_emulateDragOver:function(){if(ct){this._lastX=ct.clientX,this._lastY=ct.clientY,It();for(var t=document.elementFromPoint(ct.clientX,ct.clientY),e=t;t&&t.shadowRoot&&(t=t.shadowRoot.elementFromPoint(ct.clientX,ct.clientY))!==e;)e=t;if(V.parentNode[L]._isOutsideThisEl(t),e)do{if(e[L]&&e[L]._onDragOver({clientX:ct.clientX,clientY:ct.clientY,target:t,rootEl:e})&&!this.options.dragoverBubble)break}while(e=m(t=e));Rt()}},_onTouchMove:function(t){if(lt){var e=(n=this.options).fallbackTolerance,i=n.fallbackOffset,s=t.touches?t.touches[0]:t,r=X&&w(X,!0),a=X&&r&&r.a,o=X&&r&&r.d,n=zt&&vt&&F(vt);a=(s.clientX-lt.clientX+i.x)/(a||1)+(n?n[0]-kt[0]:0)/(a||1),o=(s.clientY-lt.clientY+i.y)/(o||1)+(n?n[1]-kt[1]:0)/(o||1);if(!Pt.active&&!yt){if(e&&Math.max(Math.abs(s.clientX-this._lastX),Math.abs(s.clientY-this._lastY))<e)return;this._onDragStart(t,!0)}X&&(r?(r.e+=a-(dt||0),r.f+=o-(ht||0)):r={a:1,b:0,c:0,d:1,e:a,f:o},r="matrix(".concat(r.a,",").concat(r.b,",").concat(r.c,",").concat(r.d,",").concat(r.e,",").concat(r.f,")"),$(X,"webkitTransform",r),$(X,"mozTransform",r),$(X,"msTransform",r),$(X,"transform",r),dt=a,ht=o,ct=s),t.cancelable&&t.preventDefault()}},_appendGhost:function(){if(!X){var t=this.options.fallbackOnBody?document.body:Z,e=C(V,!0,zt,!0,t),i=this.options;if(zt){for(vt=t;"static"===$(vt,"position")&&"none"===$(vt,"transform")&&vt!==document;)vt=vt.parentNode;vt!==document.body&&vt!==document.documentElement?(vt===document&&(vt=S()),e.top+=vt.scrollTop,e.left+=vt.scrollLeft):vt=S(),kt=F(vt)}b(X=V.cloneNode(!0),i.ghostClass,!1),b(X,i.fallbackClass,!0),b(X,i.dragClass,!0),$(X,"transition",""),$(X,"transform",""),$(X,"box-sizing","border-box"),$(X,"margin",0),$(X,"top",e.top),$(X,"left",e.left),$(X,"width",e.width),$(X,"height",e.height),$(X,"opacity","0.8"),$(X,"position",zt?"absolute":"fixed"),$(X,"zIndex","100000"),$(X,"pointerEvents","none"),Pt.ghost=X,t.appendChild(X),$(X,"transform-origin",pt/parseInt(X.style.width)*100+"% "+gt/parseInt(X.style.height)*100+"%")}},_onDragStart:function(t,e){var i=this,s=t.dataTransfer,r=i.options;G("dragStart",this,{evt:t}),Pt.eventCanceled?this._onDrop():(G("setupClone",this),Pt.eventCanceled||((tt=N(V)).removeAttribute("id"),tt.draggable=!1,tt.style["will-change"]="",this._hideClone(),b(tt,this.options.chosenClass,!1),Pt.clone=tt),i.cloneId=Wt(function(){G("clone",i),Pt.eventCanceled||(i.options.removeCloneOnHide||Z.insertBefore(tt,V),i._hideClone(),q({sortable:i,name:"clone"}))}),e||b(V,r.dragClass,!0),e?(xt=!0,i._loopId=setInterval(i._emulateDragOver,50)):(u(document,"mouseup",i._onDrop),u(document,"touchend",i._onDrop),u(document,"touchcancel",i._onDrop),s&&(s.effectAllowed="move",r.setData&&r.setData.call(i,s,V)),_(document,"drop",i),$(V,"transform","translateZ(0)")),yt=!0,i._dragStartId=Wt(i._dragStarted.bind(i,e,t)),_(document,"selectstart",i),_t=!0,window.getSelection().removeAllRanges(),d&&$(document.body,"user-select","none"))},_onDragOver:function(t){var i,s,r,a,o,n=this.el,l=t.target,c=this.options,d=c.group,h=Pt.active,p=ot===d,g=c.sort,_=nt||h,u=this,f=!1;if(!St){if(void 0!==t.preventDefault&&t.cancelable&&t.preventDefault(),l=v(l,c.draggable,n,!0),P("dragOver"),Pt.eventCanceled)return f;if(V.contains(t.target)||l.animated&&l.animatingX&&l.animatingY||u._ignoreWhileAnimating===l)return W(!1);if(xt=!1,h&&!c.disabled&&(p?g||(s=Y!==Z):nt===this||(this.lastPutMode=ot.checkPull(this,h,V,t))&&d.checkPut(this,h,V,t))){if(r="vertical"===this._getDirection(t,l),i=C(V),P("dragOverValid"),Pt.eventCanceled)return f;if(s)return Y=Z,U(),this._hideClone(),P("revert"),Pt.eventCanceled||(J?Z.insertBefore(V,J):Z.appendChild(V)),W(!0);var m=M(n,c.draggable);if(m&&(F=t,d=r,O=C(M((S=this).el,S.options.draggable)),S=B(S.el,S.options,X),!(d?F.clientX>S.right+10||F.clientY>O.bottom&&F.clientX>O.left:F.clientY>S.bottom+10||F.clientX>O.right&&F.clientY>O.top)||m.animated)){if(m&&(a=t,o=r,A=C(z((T=this).el,0,T.options,!0)),T=B(T.el,T.options,X),o?a.clientX<T.left-10||a.clientY<A.top&&a.clientX<A.right:a.clientY<T.top-10||a.clientY<A.bottom&&a.clientX<A.left)){if((I=z(n,0,c,!0))===V)return W(!1);if(k=C(l=I),!1!==Bt(Z,n,V,i,l,k,t,!1))return U(),n.insertBefore(V,I),Y=n,H(),W(!0)}else if(l.parentNode===n){var y,x,w,k=C(l),S=V.parentNode!==n,F=(F=V.animated&&V.toRect||i,O=l.animated&&l.toRect||k,T=(o=r)?F.left:F.top,a=o?F.right:F.bottom,A=o?F.width:F.height,I=o?O.left:O.top,F=o?O.right:O.bottom,O=o?O.width:O.height,!(T===I||a===F||T+A/2===I+O/2)),T=r?"top":"left",A=E(l,"top","top")||E(V,"top","top"),I=A?A.scrollTop:void 0;if(ut!==l&&(x=k[T],$t=!1,wt=!F&&c.invertSwap||S),0!==(y=function(t,e,i,s,r,a,o,n){var l=s?t.clientY:t.clientX,c=s?i.height:i.width;t=s?i.top:i.left,s=s?i.bottom:i.right,i=!1;if(!o)if(n&&mt<c*r){if($t=!$t&&(1===ft?t+c*a/2<l:l<s-c*a/2)||$t)i=!0;else if(1===ft?l<t+mt:s-mt<l)return-ft}else if(t+c*(1-r)/2<l&&l<s-c*(1-r)/2)return function(t){return D(V)<D(t)?1:-1}(e);return(i=i||o)&&(l<t+c*a/2||s-c*a/2<l)?t+c/2<l?1:-1:0}(t,l,k,r,F?1:c.swapThreshold,null==c.invertedSwapThreshold?c.swapThreshold:c.invertedSwapThreshold,wt,ut===l)))for(var N=D(V);(w=Y.children[N-=y])&&("none"===$(w,"display")||w===X););if(0===y||w===l)return W(!1);ft=y;var O=(ut=l).nextElementSibling;S=!1;if(!1!==(F=Bt(Z,n,V,i,l,k,t,S=1===y)))return 1!==F&&-1!==F||(S=1===F),St=!0,setTimeout(Ut,30),U(),S&&!O?n.appendChild(V):l.parentNode.insertBefore(V,S?O:l),A&&R(A,0,I-A.scrollTop),Y=V.parentNode,void 0===x||wt||(mt=Math.abs(x-C(l)[T])),H(),W(!0)}}else{if(m===V)return W(!1);if((l=m&&n===t.target?m:l)&&(k=C(l)),!1!==Bt(Z,n,V,i,l,k,t,!!l))return U(),m&&m.nextSibling?n.insertBefore(V,m.nextSibling):n.appendChild(V),Y=n,H(),W(!0)}if(n.contains(V))return W(!1)}return!1}function P(a,o){G(a,u,e({evt:t,isOwner:p,axis:r?"vertical":"horizontal",revert:s,dragRect:i,targetRect:k,canSort:g,fromSortable:_,target:l,completed:W,onMove:function(e,s){return Bt(Z,n,V,i,e,C(e),t,s)},changed:H},o))}function U(){P("dragOverAnimationCapture"),u.captureAnimationState(),u!==_&&_.captureAnimationState()}function W(e){return P("dragOverCompleted",{insertion:e}),e&&(p?h._hideClone():h._showClone(u),u!==_&&(b(V,(nt||h).options.ghostClass,!1),b(V,c.ghostClass,!0)),nt!==u&&u!==Pt.active?nt=u:u===Pt.active&&nt&&(nt=null),_===u&&(u._ignoreWhileAnimating=l),u.animateAll(function(){P("dragOverAnimationComplete"),u._ignoreWhileAnimating=null}),u!==_&&(_.animateAll(),_._ignoreWhileAnimating=null)),(l===V&&!V.animated||l===n&&!l.animated)&&(ut=null),c.dragoverBubble||t.rootEl||l===document||(V.parentNode[L]._isOutsideThisEl(t.target),e||Nt(t)),!c.dragoverBubble&&t.stopPropagation&&t.stopPropagation(),f=!0}function H(){st=D(V),at=D(V,c.draggable),q({sortable:u,name:"change",toEl:n,newIndex:st,newDraggableIndex:at,originalEvent:t})}},_ignoreWhileAnimating:null,_offMoveEvents:function(){u(document,"mousemove",this._onTouchMove),u(document,"touchmove",this._onTouchMove),u(document,"pointermove",this._onTouchMove),u(document,"dragover",Nt),u(document,"mousemove",Nt),u(document,"touchmove",Nt)},_offUpEvents:function(){var t=this.el.ownerDocument;u(t,"mouseup",this._onDrop),u(t,"touchend",this._onDrop),u(t,"pointerup",this._onDrop),u(t,"pointercancel",this._onDrop),u(t,"touchcancel",this._onDrop),u(document,"selectstart",this)},_onDrop:function(t){var e=this.el,i=this.options;st=D(V),at=D(V,i.draggable),G("drop",this,{evt:t}),Y=V&&V.parentNode,st=D(V),at=D(V,i.draggable),Pt.eventCanceled||($t=wt=yt=!1,clearInterval(this._loopId),clearTimeout(this._dragStartTimer),Ht(this.cloneId),Ht(this._dragStartId),this.nativeDraggable&&(u(document,"drop",this),u(e,"dragstart",this._onDragStart)),this._offMoveEvents(),this._offUpEvents(),d&&$(document.body,"user-select",""),$(V,"transform",""),t&&(_t&&(t.cancelable&&t.preventDefault(),i.dropBubble||t.stopPropagation()),X&&X.parentNode&&X.parentNode.removeChild(X),(Z===Y||nt&&"clone"!==nt.lastPutMode)&&tt&&tt.parentNode&&tt.parentNode.removeChild(tt),V&&(this.nativeDraggable&&u(V,"dragend",this),Lt(V),V.style["will-change"]="",_t&&!yt&&b(V,(nt||this).options.ghostClass,!1),b(V,this.options.chosenClass,!1),q({sortable:this,name:"unchoose",toEl:Y,newIndex:null,newDraggableIndex:null,originalEvent:t}),Z!==Y?(0<=st&&(q({rootEl:Y,name:"add",toEl:Y,fromEl:Z,originalEvent:t}),q({sortable:this,name:"remove",toEl:Y,originalEvent:t}),q({rootEl:Y,name:"sort",toEl:Y,fromEl:Z,originalEvent:t}),q({sortable:this,name:"sort",toEl:Y,originalEvent:t})),nt&&nt.save()):st!==it&&0<=st&&(q({sortable:this,name:"update",toEl:Y,originalEvent:t}),q({sortable:this,name:"sort",toEl:Y,originalEvent:t})),Pt.active&&(null!=st&&-1!==st||(st=it,at=rt),q({sortable:this,name:"end",toEl:Y,originalEvent:t}),this.save())))),this._nulling()},_nulling:function(){G("nulling",this),Z=V=Y=X=J=tt=Q=et=lt=ct=_t=st=at=it=rt=ut=ft=nt=ot=Pt.dragged=Pt.ghost=Pt.clone=Pt.active=null,Ct.forEach(function(t){t.checked=!0}),Ct.length=dt=ht=0},handleEvent:function(t){switch(t.type){case"drop":case"dragend":this._onDrop(t);break;case"dragenter":case"dragover":V&&(this._onDragOver(t),function(t){t.dataTransfer&&(t.dataTransfer.dropEffect="move"),t.cancelable&&t.preventDefault()}(t));break;case"selectstart":t.preventDefault()}},toArray:function(){for(var t,e=[],i=this.el.children,s=0,r=i.length,a=this.options;s<r;s++)v(t=i[s],a.draggable,this.el,!1)&&e.push(t.getAttribute(a.dataIdAttr)||function(t){for(var e=t.tagName+t.className+t.src+t.href+t.textContent,i=e.length,s=0;i--;)s+=e.charCodeAt(i);return s.toString(36)}(t));return e},sort:function(t,e){var i={},s=this.el;this.toArray().forEach(function(t,e){v(e=s.children[e],this.options.draggable,s,!1)&&(i[t]=e)},this),e&&this.captureAnimationState(),t.forEach(function(t){i[t]&&(s.removeChild(i[t]),s.appendChild(i[t]))}),e&&this.animateAll()},save:function(){var t=this.options.store;t&&t.set&&t.set(this)},closest:function(t,e){return v(t,e||this.options.draggable,this.el,!1)},option:function(t,e){var i=this.options;if(void 0===e)return i[t];var s=H.modifyOption(this,t,e);i[t]=void 0!==s?s:e,"group"===t&&At(i)},destroy:function(){G("destroy",this);var t=this.el;t[L]=null,u(t,"mousedown",this._onTapStart),u(t,"touchstart",this._onTapStart),u(t,"pointerdown",this._onTapStart),this.nativeDraggable&&(u(t,"dragover",this),u(t,"dragenter",this)),Array.prototype.forEach.call(t.querySelectorAll("[draggable]"),function(t){t.removeAttribute("draggable")}),this._onDrop(),this._disableDelayedDragEvents(),bt.splice(bt.indexOf(this.el),1),this.el=t=null},_hideClone:function(){et||(G("hideClone",this),Pt.eventCanceled||($(tt,"display","none"),this.options.removeCloneOnHide&&tt.parentNode&&tt.parentNode.removeChild(tt),et=!0))},_showClone:function(t){"clone"===t.lastPutMode?et&&(G("showClone",this),Pt.eventCanceled||(V.parentNode!=Z||this.options.group.revertClone?J?Z.insertBefore(tt,J):Z.appendChild(tt):Z.insertBefore(tt,V),this.options.group.revertClone&&this.animate(V,tt),$(tt,"display",""),et=!1)):this._hideClone()}},Et&&_(document,"touchmove",function(t){(Pt.active||yt)&&t.cancelable&&t.preventDefault()}),Pt.utils={on:_,off:u,css:$,find:k,is:function(t,e){return!!v(t,e,t,!1)},extend:function(t,e){if(t&&e)for(var i in e)e.hasOwnProperty(i)&&(t[i]=e[i]);return t},throttle:I,closest:v,toggleClass:b,clone:N,index:D,nextTick:Wt,cancelNextTick:Ht,detectDirection:Tt,getChild:z,expando:L},Pt.get=function(t){return t[L]},Pt.mount=function(){for(var t=arguments.length,i=new Array(t),s=0;s<t;s++)i[s]=arguments[s];(i=i[0].constructor===Array?i[0]:i).forEach(function(t){if(!t.prototype||!t.prototype.constructor)throw"Sortable: Mounted plugin must be a constructor function, not ".concat({}.toString.call(t));t.utils&&(Pt.utils=e(e({},Pt.utils),t.utils)),H.mount(t)})},Pt.create=function(t,e){return new Pt(t,e)};var jt,Gt,Kt,qt,Vt,Yt,Xt=[],Zt=!(Pt.version="1.15.6");function Jt(){Xt.forEach(function(t){clearInterval(t.pid)}),Xt=[]}function Qt(){clearInterval(Yt)}var te,ee=I(function(t,e,i,s){if(e.scroll){var r,a=(t.touches?t.touches[0]:t).clientX,o=(t.touches?t.touches[0]:t).clientY,n=e.scrollSensitivity,l=e.scrollSpeed,c=S(),d=!1;Gt!==i&&(Gt=i,Jt(),jt=e.scroll,r=e.scrollFn,!0===jt&&(jt=T(i,!0)));var h=0,p=jt;do{var g=p,_=(z=C(g)).top,u=z.bottom,f=z.left,m=z.right,v=z.width,y=z.height,x=void 0,b=g.scrollWidth,w=g.scrollHeight,k=$(g),E=g.scrollLeft,z=g.scrollTop,M=g===c?(x=v<b&&("auto"===k.overflowX||"scroll"===k.overflowX||"visible"===k.overflowX),y<w&&("auto"===k.overflowY||"scroll"===k.overflowY||"visible"===k.overflowY)):(x=v<b&&("auto"===k.overflowX||"scroll"===k.overflowX),y<w&&("auto"===k.overflowY||"scroll"===k.overflowY));E=x&&(Math.abs(m-a)<=n&&E+v<b)-(Math.abs(f-a)<=n&&!!E),z=M&&(Math.abs(u-o)<=n&&z+y<w)-(Math.abs(_-o)<=n&&!!z);if(!Xt[h])for(var D=0;D<=h;D++)Xt[D]||(Xt[D]={});Xt[h].vx==E&&Xt[h].vy==z&&Xt[h].el===g||(Xt[h].el=g,Xt[h].vx=E,Xt[h].vy=z,clearInterval(Xt[h].pid),0==E&&0==z||(d=!0,Xt[h].pid=setInterval(function(){s&&0===this.layer&&Pt.active._onTouchMove(Vt);var e=Xt[this.layer].vy?Xt[this.layer].vy*l:0,i=Xt[this.layer].vx?Xt[this.layer].vx*l:0;"function"==typeof r&&"continue"!==r.call(Pt.dragged.parentNode[L],i,e,t,Vt,Xt[this.layer].el)||R(Xt[this.layer].el,i,e)}.bind({layer:h}),24))),h++}while(e.bubbleScroll&&p!==c&&(p=T(p,!1)));Zt=d}},30);p=function(t){var e=t.originalEvent,i=t.putSortable,s=t.dragEl,r=t.activeSortable,a=t.dispatchSortableEvent,o=t.hideGhostForTarget;t=t.unhideGhostForTarget;e&&(r=i||r,o(),e=e.changedTouches&&e.changedTouches.length?e.changedTouches[0]:e,e=document.elementFromPoint(e.clientX,e.clientY),t(),r&&!r.el.contains(e)&&(a("spill"),this.onSpill({dragEl:s,putSortable:i})))};function ie(){}function se(){}ie.prototype={startIndex:null,dragStart:function(t){t=t.oldDraggableIndex,this.startIndex=t},onSpill:function(t){var e=t.dragEl,i=t.putSortable;this.sortable.captureAnimationState(),i&&i.captureAnimationState(),(t=z(this.sortable.el,this.startIndex,this.options))?this.sortable.el.insertBefore(e,t):this.sortable.el.appendChild(e),this.sortable.animateAll(),i&&i.animateAll()},drop:p},s(ie,{pluginName:"revertOnSpill"}),se.prototype={onSpill:function(t){var e=t.dragEl;(t=t.putSortable||this.sortable).captureAnimationState(),e.parentNode&&e.parentNode.removeChild(e),t.animateAll()},drop:p},s(se,{pluginName:"removeOnSpill"});var re,ae,oe,ne,le,ce=[],de=[],he=!1,pe=!1,ge=!1;function _e(t,e){de.forEach(function(i,s){(s=e.children[i.sortableIndex+(t?Number(s):0)])?e.insertBefore(i,s):e.appendChild(i)})}function ue(){ce.forEach(function(t){t!==oe&&t.parentNode&&t.parentNode.removeChild(t)})}return Pt.mount(new function(){function t(){for(var t in this.defaults={scroll:!0,forceAutoScrollFallback:!1,scrollSensitivity:30,scrollSpeed:10,bubbleScroll:!0},this)"_"===t.charAt(0)&&"function"==typeof this[t]&&(this[t]=this[t].bind(this))}return t.prototype={dragStarted:function(t){t=t.originalEvent,this.sortable.nativeDraggable?_(document,"dragover",this._handleAutoScroll):this.options.supportPointer?_(document,"pointermove",this._handleFallbackAutoScroll):t.touches?_(document,"touchmove",this._handleFallbackAutoScroll):_(document,"mousemove",this._handleFallbackAutoScroll)},dragOverCompleted:function(t){t=t.originalEvent,this.options.dragOverBubble||t.rootEl||this._handleAutoScroll(t)},drop:function(){this.sortable.nativeDraggable?u(document,"dragover",this._handleAutoScroll):(u(document,"pointermove",this._handleFallbackAutoScroll),u(document,"touchmove",this._handleFallbackAutoScroll),u(document,"mousemove",this._handleFallbackAutoScroll)),Qt(),Jt(),clearTimeout(y),y=void 0},nulling:function(){Vt=Gt=jt=Zt=Yt=Kt=qt=null,Xt.length=0},_handleFallbackAutoScroll:function(t){this._handleAutoScroll(t,!0)},_handleAutoScroll:function(t,e){var i,s=this,r=(t.touches?t.touches[0]:t).clientX,a=(t.touches?t.touches[0]:t).clientY,o=document.elementFromPoint(r,a);Vt=t,e||this.options.forceAutoScrollFallback||l||n||d?(ee(t,this.options,o,e),i=T(o,!0),!Zt||Yt&&r===Kt&&a===qt||(Yt&&Qt(),Yt=setInterval(function(){var o=T(document.elementFromPoint(r,a),!0);o!==i&&(i=o,Jt()),ee(t,s.options,o,e)},10),Kt=r,qt=a)):this.options.bubbleScroll&&T(o,!0)!==S()?ee(t,this.options,T(o,!1),!1):Jt()}},s(t,{pluginName:"scroll",initializeByDefault:!0})}),Pt.mount(se,ie),Pt.mount(new function(){function t(){this.defaults={swapClass:"sortable-swap-highlight"}}return t.prototype={dragStart:function(t){t=t.dragEl,te=t},dragOverValid:function(t){var e=t.completed,i=t.target,s=t.onMove,r=t.activeSortable,a=t.changed,o=t.cancel;r.options.swap&&(t=this.sortable.el,r=this.options,i&&i!==t&&(t=te,te=!1!==s(i)?(b(i,r.swapClass,!0),i):null,t&&t!==te&&b(t,r.swapClass,!1)),a(),e(!0),o())},drop:function(t){var e,i,s=t.activeSortable,r=t.putSortable,a=t.dragEl,o=r||this.sortable,n=this.options;te&&b(te,n.swapClass,!1),te&&(n.swap||r&&r.options.swap)&&a!==te&&(o.captureAnimationState(),o!==s&&s.captureAnimationState(),i=te,t=(e=a).parentNode,n=i.parentNode,t&&n&&!t.isEqualNode(i)&&!n.isEqualNode(e)&&(r=D(e),a=D(i),t.isEqualNode(n)&&r<a&&a++,t.insertBefore(i,t.children[r]),n.insertBefore(e,n.children[a])),o.animateAll(),o!==s&&s.animateAll())},nulling:function(){te=null}},s(t,{pluginName:"swap",eventProperties:function(){return{swapItem:te}}})}),Pt.mount(new function(){function t(t){for(var e in this)"_"===e.charAt(0)&&"function"==typeof this[e]&&(this[e]=this[e].bind(this));t.options.avoidImplicitDeselect||(t.options.supportPointer?_(document,"pointerup",this._deselectMultiDrag):(_(document,"mouseup",this._deselectMultiDrag),_(document,"touchend",this._deselectMultiDrag))),_(document,"keydown",this._checkKeyDown),_(document,"keyup",this._checkKeyUp),this.defaults={selectedClass:"sortable-selected",multiDragKey:null,avoidImplicitDeselect:!1,setData:function(e,i){var s="";ce.length&&ae===t?ce.forEach(function(t,e){s+=(e?", ":"")+t.textContent}):s=i.textContent,e.setData("Text",s)}}}return t.prototype={multiDragKeyDown:!1,isMultiDrag:!1,delayStartGlobal:function(t){t=t.dragEl,oe=t},delayEnded:function(){this.isMultiDrag=~ce.indexOf(oe)},setupClone:function(t){var e=t.sortable;t=t.cancel;if(this.isMultiDrag){for(var i=0;i<ce.length;i++)de.push(N(ce[i])),de[i].sortableIndex=ce[i].sortableIndex,de[i].draggable=!1,de[i].style["will-change"]="",b(de[i],this.options.selectedClass,!1),ce[i]===oe&&b(de[i],this.options.chosenClass,!1);e._hideClone(),t()}},clone:function(t){var e=t.sortable,i=t.rootEl,s=t.dispatchSortableEvent;t=t.cancel;this.isMultiDrag&&(this.options.removeCloneOnHide||ce.length&&ae===e&&(_e(!0,i),s("clone"),t()))},showClone:function(t){var e=t.cloneNowShown,i=t.rootEl;t=t.cancel;this.isMultiDrag&&(_e(!1,i),de.forEach(function(t){$(t,"display","")}),e(),le=!1,t())},hideClone:function(t){var e=this,i=(t.sortable,t.cloneNowHidden);t=t.cancel;this.isMultiDrag&&(de.forEach(function(t){$(t,"display","none"),e.options.removeCloneOnHide&&t.parentNode&&t.parentNode.removeChild(t)}),i(),le=!0,t())},dragStartGlobal:function(t){t.sortable,!this.isMultiDrag&&ae&&ae.multiDrag._deselectMultiDrag(),ce.forEach(function(t){t.sortableIndex=D(t)}),ce=ce.sort(function(t,e){return t.sortableIndex-e.sortableIndex}),ge=!0},dragStarted:function(t){var e,i=this;t=t.sortable;this.isMultiDrag&&(this.options.sort&&(t.captureAnimationState(),this.options.animation&&(ce.forEach(function(t){t!==oe&&$(t,"position","absolute")}),e=C(oe,!1,!0,!0),ce.forEach(function(t){t!==oe&&O(t,e)}),he=pe=!0)),t.animateAll(function(){he=pe=!1,i.options.animation&&ce.forEach(function(t){P(t)}),i.options.sort&&ue()}))},dragOver:function(t){var e=t.target,i=t.completed;t=t.cancel;pe&&~ce.indexOf(e)&&(i(!1),t())},revert:function(t){var e,i,s=t.fromSortable,r=t.rootEl,a=t.sortable,o=t.dragRect;1<ce.length&&(ce.forEach(function(t){a.addAnimationState({target:t,rect:pe?C(t):o}),P(t),t.fromRect=o,s.removeAnimationState(t)}),pe=!1,e=!this.options.removeCloneOnHide,i=r,ce.forEach(function(t,s){(s=i.children[t.sortableIndex+(e?Number(s):0)])?i.insertBefore(t,s):i.appendChild(t)}))},dragOverCompleted:function(t){var e,i=t.sortable,s=t.isOwner,r=t.insertion,a=t.activeSortable,o=t.parentEl,n=t.putSortable;t=this.options;r&&(s&&a._hideClone(),he=!1,t.animation&&1<ce.length&&(pe||!s&&!a.options.sort&&!n)&&(e=C(oe,!1,!0,!0),ce.forEach(function(t){t!==oe&&(O(t,e),o.appendChild(t))}),pe=!0),s||(pe||ue(),1<ce.length?(s=le,a._showClone(i),a.options.animation&&!le&&s&&de.forEach(function(t){a.addAnimationState({target:t,rect:ne}),t.fromRect=ne,t.thisAnimationDuration=null})):a._showClone(i)))},dragOverAnimationCapture:function(t){var e=t.dragRect,i=t.isOwner;t=t.activeSortable;ce.forEach(function(t){t.thisAnimationDuration=null}),t.options.animation&&!i&&t.multiDrag.isMultiDrag&&(ne=s({},e),e=w(oe,!0),ne.top-=e.f,ne.left-=e.e)},dragOverAnimationComplete:function(){pe&&(pe=!1,ue())},drop:function(t){var e,i,s,r,a,o,n,l=t.originalEvent,c=t.rootEl,d=t.parentEl,h=t.sortable,p=t.dispatchSortableEvent,g=t.oldIndex,_=(t=t.putSortable)||this.sortable;l&&(e=this.options,i=d.children,ge||(e.multiDragKey&&!this.multiDragKeyDown&&this._deselectMultiDrag(),b(oe,e.selectedClass,!~ce.indexOf(oe)),~ce.indexOf(oe)?(ce.splice(ce.indexOf(oe),1),re=null,j({sortable:h,rootEl:c,name:"deselect",targetEl:oe,originalEvent:l})):(ce.push(oe),j({sortable:h,rootEl:c,name:"select",targetEl:oe,originalEvent:l}),l.shiftKey&&re&&h.el.contains(re)?(s=D(re),r=D(oe),~s&&~r&&s!==r&&function(){for(var t,a=s<r?(t=s,r):(t=r,s+1),o=e.filter;t<a;t++)~ce.indexOf(i[t])||v(i[t],e.draggable,d,!1)&&(o&&("function"==typeof o?o.call(h,l,i[t],h):o.split(",").some(function(e){return v(i[t],e.trim(),d,!1)}))||(b(i[t],e.selectedClass,!0),ce.push(i[t]),j({sortable:h,rootEl:c,name:"select",targetEl:i[t],originalEvent:l})))}()):re=oe,ae=_)),ge&&this.isMultiDrag&&(pe=!1,(d[L].options.sort||d!==c)&&1<ce.length&&(a=C(oe),o=D(oe,":not(."+this.options.selectedClass+")"),!he&&e.animation&&(oe.thisAnimationDuration=null),_.captureAnimationState(),he||(e.animation&&(oe.fromRect=a,ce.forEach(function(t){var e;t.thisAnimationDuration=null,t!==oe&&(e=pe?C(t):a,t.fromRect=e,_.addAnimationState({target:t,rect:e}))})),ue(),ce.forEach(function(t){i[o]?d.insertBefore(t,i[o]):d.appendChild(t),o++}),g===D(oe)&&(n=!1,ce.forEach(function(t){t.sortableIndex!==D(t)&&(n=!0)}),n&&(p("update"),p("sort")))),ce.forEach(function(t){P(t)}),_.animateAll()),ae=_),(c===d||t&&"clone"!==t.lastPutMode)&&de.forEach(function(t){t.parentNode&&t.parentNode.removeChild(t)}))},nullingGlobal:function(){this.isMultiDrag=ge=!1,de.length=0},destroyGlobal:function(){this._deselectMultiDrag(),u(document,"pointerup",this._deselectMultiDrag),u(document,"mouseup",this._deselectMultiDrag),u(document,"touchend",this._deselectMultiDrag),u(document,"keydown",this._checkKeyDown),u(document,"keyup",this._checkKeyUp)},_deselectMultiDrag:function(t){if(!(void 0!==ge&&ge||ae!==this.sortable||t&&v(t.target,this.options.draggable,this.sortable.el,!1)||t&&0!==t.button))for(;ce.length;){var e=ce[0];b(e,this.options.selectedClass,!1),ce.shift(),j({sortable:this.sortable,rootEl:this.sortable.el,name:"deselect",targetEl:e,originalEvent:t})}},_checkKeyDown:function(t){t.key===this.options.multiDragKey&&(this.multiDragKeyDown=!0)},_checkKeyUp:function(t){t.key===this.options.multiDragKey&&(this.multiDragKeyDown=!1)}},s(t,{pluginName:"multiDrag",utils:{select:function(t){var e=t.parentNode[L];e&&e.options.multiDrag&&!~ce.indexOf(t)&&(ae&&ae!==e&&(ae.multiDrag._deselectMultiDrag(),ae=e),b(t,e.options.selectedClass,!0),ce.push(t))},deselect:function(t){var e=t.parentNode[L],i=ce.indexOf(t);e&&e.options.multiDrag&&~i&&(b(t,e.options.selectedClass,!1),ce.splice(i,1))}},eventProperties:function(){var t=this,e=[],i=[];return ce.forEach(function(s){var r;e.push({multiDragElement:s,index:s.sortableIndex}),r=pe&&s!==oe?-1:pe?D(s,":not(."+t.options.selectedClass+")"):D(s),i.push({multiDragElement:s,index:r})}),{items:r(ce),clones:[].concat(de),oldIndicies:e,newIndicies:i}},optionListeners:{multiDragKey:function(t){return"ctrl"===(t=t.toLowerCase())?t="Control":1<t.length&&(t=t.charAt(0).toUpperCase()+t.substr(1)),t}}})}),Pt})}();const ge=Promise.resolve(window.Sortable);ft("sem-load-priority-card",class extends mt{constructor(){super(),this.devices=[],this.targetPeakLimit=5,this.currentPeak=0,this.loadManagementStatus="normal",this._sortable=null,this._interacting=!1,this._lastDeviceSig=""}setConfig(t){this._config=t,this.entityPrefix=t.entity_prefix||"sensor.sem_",this.requestUpdate()}set hass(t){this._hass,this._hass=t;const e=t?.language;if(e!==this._lang)return this._lang=e,this._lastDeviceSig="",void this.requestUpdate();if(this._interacting)return;if(this._isFrozen())return;const i=t?.states[`${this.entityPrefix}controllable_devices_count`],s=t?.states[`${this.entityPrefix}consecutive_peak_15min`],r=t?.states[`${this.entityPrefix}load_management_status`],a=(i?.state||"")+"|"+(s?.state||"")+"|"+(r?.state||"");a!==this._lastKey&&(this._lastKey=a,this._updateDeviceData(),this.requestUpdate())}get hass(){return this._hass}disconnectedCallback(){super.disconnectedCallback(),this._sortable&&(this._sortable.destroy(),this._sortable=null)}async firstUpdated(){await this._initSortable(),this._bindEvents()}async updated(t){const e=this.devices.map(t=>t.id).join(",");e!==this._lastDeviceSig&&(this._lastDeviceSig=e,this._sortable&&(this._sortable.destroy(),this._sortable=null),await this._initSortable(),this._bindEvents())}static get styles(){return a`
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
            .status-bar { display:flex; align-items:center; gap:8px; margin-bottom:12px; padding-bottom:10px; border-bottom:1px solid var(--divider-color, rgba(128,128,128,0.12)); font-size:0.85em; }
            .status-text { text-transform:uppercase; letter-spacing:0.5px; font-weight:600; opacity:0.85; }
            .peak-dot { width:9px; height:9px; border-radius:50%; }
            .peak-box { background:var(--secondary-background-color, rgba(255,255,255,0.04)); border:1px solid var(--divider-color, rgba(255,255,255,0.08)); border-radius:12px; padding:12px; margin-bottom:10px; backdrop-filter: blur(8px); }
            .peak-row { display:flex; justify-content:space-between; margin-bottom:4px; font-size:0.9em; }
            .peak-row:last-of-type { margin-bottom:0; }
            .dim { opacity:0.55; font-size:0.9em; }
            .mono { font-variant-numeric:tabular-nums; font-weight:500; }
            .bar { width:100%; height:5px; background:var(--divider-color, rgba(128,128,128,0.12)); border-radius:3px; overflow:hidden; margin-top:8px; }
            .bar-fill { height:100%; border-radius:3px; transition:width 0.4s ease, background 0.4s ease; }
            .target-row { display:flex; align-items:center; gap:8px; margin-top:6px; }
            .target-row input { width:70px; padding:5px 8px; border:1px solid var(--divider-color, rgba(255,255,255,0.08)); border-radius:8px; background:var(--card-background-color, rgba(0,0,0,0.2)); color:var(--primary-text-color); text-align:center; font-size:0.9em; }
            .target-row input:focus { outline:none; border-color:#ff9800; }
            .target-row button { padding:5px 14px; border:none; border-radius:8px; background:#ff9800; color:#fff; cursor:pointer; font-size:0.85em; }
            .target-row button:hover { background:#e68900; }
            .section-label { font-size:0.85em; opacity:0.55; margin-bottom:10px; display:flex; align-items:center; gap:6px; }
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
            .device-power { font-size:0.9em; font-weight:500; font-variant-numeric:tabular-nums; white-space:nowrap; opacity:0.7; }
            .device-bottom { display:flex; align-items:center; gap:8px; font-size:0.8em; flex-wrap:wrap; }
            .status-dot { width:7px; height:7px; border-radius:50%; background:var(--divider-color, rgba(128,128,128,0.12)); flex-shrink:0; }
            .status-dot.on { background:#4caf50; box-shadow:0 0 6px #4caf50; }
            .status-dot.shed { background:#f44336; box-shadow:0 0 6px #f44336; }
            .spacer { flex:1; }
            .badge { padding:2px 7px; border-radius:8px; font-size:0.8em; font-weight:600; }
            .badge.priority { background:#ff9800; color:#fff; min-width:14px; text-align:center; }
            .toggle-label { display:flex; align-items:center; gap:4px; }
            .arrows { display:flex; flex-direction:column; gap:1px; }
            .arrow-btn { border:none; background:none; cursor:pointer; font-size:10px; padding:0 4px; opacity:0.35; line-height:1; color:var(--primary-text-color,inherit); }
            .arrow-btn:hover { opacity:0.8; }
            .mode-select { background:var(--card-background-color,rgba(40,40,55,0.7)); color:var(--primary-text-color); border:1px solid var(--divider-color,rgba(255,255,255,0.08)); border-radius:6px; padding:2px 6px; font-size:11px; font-family:'Segoe UI','Roboto',sans-serif; cursor:pointer; -webkit-appearance:none; appearance:none; }
            .mode-select:focus { outline:none; border-color:rgba(255,152,0,0.5); }
            .configure-btn { display:inline-flex; align-items:center; gap:3px; padding:2px 6px; background:rgba(255,193,7,0.12); border:1px solid rgba(255,193,7,0.25); border-radius:5px; color:#ffc107; cursor:pointer; font-size:0.75em; }
            .configure-btn:hover { background:rgba(255,193,7,0.22); }
            .hint { text-align:center; font-size:0.8em; opacity:0.4; margin-top:10px; }
            .empty { text-align:center; padding:20px 0; opacity:0.4; font-size:0.9em; }
        `}_updateDeviceData(){if(!this._hass)return;const t=this._hass.states[`${this.entityPrefix}target_peak_limit`],e=this._hass.states[`${this.entityPrefix}consecutive_peak_15min`],i=this._hass.states[`${this.entityPrefix}load_management_status`],s=this._hass.states[`${this.entityPrefix}controllable_devices_count`];t&&(this.targetPeakLimit=parseFloat(t.state)||5),e&&(this.currentPeak=parseFloat(e.state)||0),i&&(this.loadManagementStatus=i.state||"normal"),s?.attributes?.devices&&(this.devices=Object.entries(s.attributes.devices).map(([t,e])=>({id:t,name:e.name||t.replace(/^(load_device_|energy_dashboard_)/,"").replace(/_/g," "),power:(e.current_power||0)/1e3,priority:e.priority||5,isOn:e.is_on||!1,isShed:e.is_shed||!1,shedReason:e.shed_reason||null,isControllable:!1!==e.is_controllable,isCritical:e.is_critical||!1,deviceType:e.device_type||"unknown",isAvailable:e.is_available||!1,hasManualMapping:e.has_manual_mapping||!1,energySensor:e.energy_sensor||"",controlMode:e.control_mode||"peak_only",dependsOn:e.depends_on||[],blockedBy:e.blocked_by||null,icon:this._getDeviceIcon(e.device_type)})).sort((t,e)=>t.priority-e.priority))}render(){if(!this._config)return K;const t=this._getPeakColor(),e=this.targetPeakLimit-this.currentPeak,i=this.targetPeakLimit>0?Math.min(this.currentPeak/this.targetPeakLimit*100,100):0;return H`
            <ha-card>
                <div class="card-content">
                    <div class="status-bar">
                        <div class="peak-dot" style="background:${t};box-shadow:0 0 8px ${t}"></div>
                        <span id="lm-status" class="status-text">${(this.loadManagementStatus||"normal").toUpperCase()}</span>
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
                        ${0===this.devices.length?H`<div class="empty">${this._t("no_devices_yet")}</div>`:this.devices.map((t,e)=>this._renderDevice(t,e+1))}
                    </div>

                    ${this.devices.length>0?H`<div class="hint">${this._t("drag_hint")}</div>`:K}

                    <div class="hint" style="margin-top:12px;padding:10px;background:rgba(128,128,128,0.06);border-radius:10px">
                        ${this._t("devices_auto_discovered")}
                    </div>
                </div>
            </ha-card>
        `}_renderDevice(t,e){const i=t.isOn,s=t.dependsOn.length>0,r=this._getDependencyDepth(t),a=r>0?`margin-left:${24*r}px;border-left:2px solid rgba(255,152,0,${.3+.1*r});`:"";return H`
        <div class="device${s?" is-child":""}" data-id="${t.id}" style="${a}">
            <div class="drag-handle"
                 title="${s?this._t("locked_under_parent"):this._t("drag_to_reorder")}"
                 style="${s?"opacity:0.3;cursor:default":""}">${s?"·":"≡"}</div>
            <div class="device-body">
                <div class="device-top">
                    <div class="device-name">
                        ${s?H`<span style="color:#ff9800;font-size:12px;margin-right:4px">&#8618;</span>`:K}
                        <ha-icon icon="${t.icon}" style="--mdc-icon-size:20px;color:${i?"#ff9800":"#666"}"></ha-icon>
                        <span>${t.name}</span>
                        ${t.hasManualMapping?H`<ha-icon icon="mdi:wrench" style="--mdc-icon-size:14px;color:#ffc107;opacity:0.6"></ha-icon>`:K}
                        ${t.isControllable?K:H`<span class="configure-btn" data-action="configure" data-energy="${t.energySensor}" data-name="${t.name}">
                                <ha-icon icon="mdi:wrench" style="--mdc-icon-size:14px"></ha-icon> ${this._t("configure")}
                              </span>`}
                    </div>
                    <div class="device-power" data-field="power-${t.id}">
                        ${i?t.power.toFixed(1)+" kW":t.isShed?this._t("shed_label"):"OFF"}
                    </div>
                </div>
                ${t.blockedBy?H`<div style="font-size:11px;color:#ff9800;padding:2px 0 0 28px">&#9203; Waiting for: ${t.blockedBy}</div>`:K}
                ${t.dependsOn.length?H`<div style="font-size:11px;opacity:0.55;padding:0 0 0 28px">&#8618; ${this._t("requires")}: ${t.dependsOn.join(", ")}</div>`:K}
                ${t.isShed&&t.shedReason?H`<div style="font-size:11px;color:#f44336;padding:2px 0 0 28px">${"emergency"===t.shedReason?this._t("shed_emergency"):this._t("shed_peak")}</div>`:K}
                <div class="device-bottom">
                    <div class="status-dot ${i?"on":t.isShed?"shed":""}" data-field="status-${t.id}"></div>
                    <span class="dim" data-field="onoff-${t.id}">${i?"ON":t.isShed?this._t("shed_label"):"OFF"}</span>
                    <span class="badge priority" data-field="pri-${t.id}">${e}</span>
                    <div class="spacer"></div>
                    <label class="toggle-label" title="${this._t("mode_tooltip")}">
                        <span class="dim">${this._t("mode")}</span>
                        <select class="mode-select" data-action="control_mode" data-device="${t.id}">
                            <option value="off" ?selected="${"off"===t.controlMode}">${this._t("off")}</option>
                            <option value="peak_only" ?selected="${"peak_only"===t.controlMode}">${this._t("peak_only")}</option>
                            <option value="surplus" ?selected="${"surplus"===t.controlMode}">${this._t("surplus_mode")}</option>
                        </select>
                    </label>
                    <label class="toggle-label" title="${this._t("requires_tooltip")}">
                        <span class="dim">${this._t("requires")}</span>
                        <select class="mode-select" data-action="depends_on" data-device="${t.id}">
                            <option value="" ?selected="${!t.dependsOn.length}">${this._t("action_none")}</option>
                            ${this.devices.filter(e=>e.id!==t.id).map(e=>H`<option value="${e.id}" ?selected="${t.dependsOn.includes(e.id)}">${e.name}</option>`)}
                        </select>
                    </label>
                    <div class="arrows">
                        <button class="arrow-btn" data-action="move-up"   data-device="${t.id}" title="${this._t("move_up")}">&#9650;</button>
                        <button class="arrow-btn" data-action="move-down" data-device="${t.id}" title="${this._t("move_down")}">&#9660;</button>
                    </div>
                </div>
            </div>
        </div>`}async _initSortable(){if(this.devices.length)try{const t=await ge,e=this.renderRoot.getElementById("device-list");if(!e)return;this._sortable&&this._sortable.destroy(),this._sortable=t.create(e,{handle:".drag-handle",filter:".is-child",preventOnFilter:!1,animation:200,easing:"cubic-bezier(0.4, 0, 0.2, 1)",ghostClass:"ghost",chosenClass:"chosen",dragClass:"dragging",forceFallback:!0,fallbackTolerance:3,onStart:()=>{this._interacting=!0},onEnd:t=>{this._interacting=!1,t.oldIndex!==t.newIndex&&(this._applyReorder(),this._regroupChildren(),this.requestUpdate())}})}catch(t){console.warn("SEM: SortableJS not available, drag disabled:",t.message)}}_applyReorder(){const t=this.renderRoot.getElementById("device-list");if(!t)return;const e=Array.from(t.querySelectorAll(".device")).map(t=>t.dataset.id),i={};this.devices.forEach(t=>{i[t.id]=t}),this.devices=e.map((t,e)=>{const s=i[t];return s&&(s.priority=e+1),s}).filter(Boolean),this._sendPriorityUpdate()}_bindEvents(){const t=this.renderRoot,e=t.getElementById("setTargetBtn");e&&!e._semBound&&(e._semBound=!0,e.addEventListener("click",()=>{const e=t.getElementById("targetInput"),i=parseFloat(e?.value);i&&i>0&&i<=20&&(this.targetPeakLimit=i,this._sendTargetPeakUpdate(i),this.requestUpdate())}));const i=t=>{const e=t.target.closest("[data-action]");if(!e)return;const i=e.dataset.action,s=e.dataset.device;if("controllable"===i){const t=this.devices.find(t=>t.id===s);t&&(t.isControllable=!t.isControllable,this._sendDeviceUpdate(s,"controllable",t.isControllable),this.requestUpdate())}else"move-up"===i||"move-down"===i?this._moveDevice(s,"move-up"===i?-1:1):"configure"===i&&this._showConfigureModal(e.dataset.energy,e.dataset.name)},s=t=>{const e=t.target.closest('[data-action="control_mode"]');if(e){const t=e.dataset.device,i=this.devices.find(e=>e.id===t);return void(i&&(i.controlMode=e.value,this._sendDeviceUpdate(t,"control_mode",e.value)))}const i=t.target.closest('[data-action="depends_on"]');if(i){const t=i.dataset.device,e=this.devices.find(e=>e.id===t);if(e){const s=i.value;e.dependsOn=s?[s]:[],this._sendDeviceUpdate(t,"depends_on",s),this._regroupChildren(),this.devices.forEach((t,e)=>{t.priority=e+1}),this.requestUpdate(),this._sendPriorityUpdate()}}},r=t.querySelector("ha-card");r&&!r._semEvtBound&&(r._semEvtBound=!0,r.addEventListener("click",i),r.addEventListener("change",s))}_moveDevice(t,e){const i=this.devices.findIndex(e=>e.id===t);if(-1===i)return;const s=i+e;if(s<0||s>=this.devices.length)return;this.devices[i].dependsOn.length||([this.devices[i],this.devices[s]]=[this.devices[s],this.devices[i]],this._regroupChildren(),this.devices.forEach((t,e)=>{t.priority=e+1}),this.requestUpdate(),this._sendPriorityUpdate())}_getDependencyDepth(t){let e=0,i=t;const s=new Set;for(;i.dependsOn.length>0&&e<5;){s.add(i.id);const t=i.dependsOn[0];if(s.has(t))break;const r=this.devices.find(e=>e.id===t);if(!r)break;e++,i=r}return e}_regroupChildren(){const t=[],e=new Set,i=s=>{e.has(s.id)||(t.push(s),e.add(s.id),this.devices.filter(t=>t.dependsOn.includes(s.id)&&!e.has(t.id)).forEach(t=>i(t)))};this.devices.filter(t=>!t.dependsOn.length).forEach(t=>i(t)),this.devices.forEach(i=>{e.has(i.id)||t.push(i)}),this.devices=t}_sendPriorityUpdate(){this._hass&&this._hass.callService("solar_energy_management","update_device_priorities",{priorities:this.devices.map(t=>({device_id:t.id,priority:t.priority}))})}_sendDeviceUpdate(t,e,i){this._hass&&this._hass.callService("solar_energy_management","update_device_config",{device_id:t,property:e,value:i})}_sendTargetPeakUpdate(t){this._hass&&this._hass.callService("solar_energy_management","update_target_peak",{target_peak_limit:t})}_showConfigureModal(t,e){const i=this.renderRoot.getElementById("sem-config-modal");i&&i.remove();const s=document.createElement("div");s.id="sem-config-modal",s.style.cssText="position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:999;display:flex;align-items:center;justify-content:center",s.innerHTML=`\n            <div style="background:var(--card-background-color,#1e1e2e);border-radius:12px;padding:24px;min-width:300px;max-width:90vw;color:var(--primary-text-color,#e0e0e0)">\n                <div style="font-weight:700;margin-bottom:16px">${this._t("configure_device")}: ${e}</div>\n                <label style="font-size:13px;opacity:0.7">${this._t("control_entity")}</label>\n                <input id="cfg-entity" type="text" placeholder="switch.example" style="width:100%;padding:8px;margin:6px 0 12px;border-radius:6px;border:1px solid rgba(255,255,255,0.1);background:rgba(0,0,0,0.2);color:inherit;box-sizing:border-box">\n                <label style="font-size:13px;opacity:0.7">${this._t("control_type")}</label>\n                <select id="cfg-type" style="width:100%;padding:8px;margin:6px 0 16px;border-radius:6px;border:1px solid rgba(255,255,255,0.1);background:rgba(0,0,0,0.2);color:inherit">\n                    <option value="switch">${this._t("mode_switch")}</option>\n                    <option value="current">${this._t("mode_current")}</option>\n                </select>\n                <div style="display:flex;gap:8px;justify-content:flex-end">\n                    <button id="cfg-cancel" style="padding:8px 16px;border-radius:6px;border:none;cursor:pointer;background:rgba(255,255,255,0.1);color:inherit">${this._t("cancel")}</button>\n                    <button id="cfg-save" style="padding:8px 16px;border-radius:6px;border:none;cursor:pointer;background:#4caf50;color:white">${this._t("save")}</button>\n                </div>\n            </div>`,this.renderRoot.appendChild(s),s.addEventListener("click",t=>{t.target===s&&s.remove()}),s.querySelector("#cfg-cancel").addEventListener("click",()=>s.remove()),s.querySelector("#cfg-save").addEventListener("click",()=>{const e=s.querySelector("#cfg-entity").value.trim();if(!e)return;const i=s.querySelector("#cfg-type").value;this._hass.callService("solar_energy_management","set_device_control_mapping",{energy_sensor:t,control_entity:e,control_type:i}).then(()=>s.remove()).catch(t=>{let e=s.querySelector(".cfg-error");e||(e=document.createElement("div"),e.className="cfg-error",e.style.cssText="color:#f44336;font-size:13px;margin-top:8px",s.querySelector("div").appendChild(e)),e.textContent=t.message})})}_getPeakColor(){const t=this.targetPeakLimit>0?this.currentPeak/this.targetPeakLimit*100:0;return t>=100?"#f44336":t>=90?"#ff9800":t>=70?"#2196f3":"#4caf50"}_getDeviceIcon(t){return{ev_charger:"mdi:ev-station",ev_charging:"mdi:ev-station",heating:"mdi:radiator",heat_pump:"mdi:heat-pump",water_heater:"mdi:water-boiler",hot_water:"mdi:water-boiler",pool_pump:"mdi:pool",appliance:"mdi:washing-machine",climate:"mdi:thermostat",light:"mdi:lightbulb"}[t]||"mdi:power-plug"}getCardSize(){return Math.max(5,3+this.devices.length)}static getStubConfig(){return{entity_prefix:"sensor.sem_"}}},{type:"sem-load-priority-card",name:"SEM Load Priority Card",description:"Drag and drop interface for managing load shedding priorities",preview:!0});const _e=[{id:"ev",icon:"mdi:ev-station",color:"#8DC892",titleKey:"ev_charging_title",subtitleFn:t=>`${t._val("charging_state")||"—"} · ${t._valNum("daily_ev_energy").toFixed(1)}/${t._numVal("daily_ev_target").toFixed(0)} kWh`},{id:"surplus",icon:"mdi:solar-power",color:"#ff9800",titleKey:"surplus_control",subtitleFn:t=>{const e=t._valNum("surplus_active_devices").toFixed(0),i=t._valNum("surplus_total_devices").toFixed(0),s=t._valNum("surplus_allocated_w").toFixed(0);return`${e}/${i} ${t._t("devices")} · ${s}W`}},{id:"battery",icon:"mdi:battery-medium",color:"#4db6ac",titleKey:"battery_management",subtitleFn:t=>`SOC ${t._valNum("battery_soc").toFixed(0)}% · ${t._val("battery_status")||"—"}`},{id:"hotwater",icon:"mdi:water-thermometer",color:"#f06292",titleKey:"hot_water_title",subtitleFn:()=>""},{id:"solar",icon:"mdi:solar-panel-large",color:"#ff9800",titleKey:"solar_power_section",subtitleFn:()=>""},{id:"tariff",icon:"mdi:cash-multiple",color:"#96CAEE",titleKey:"tariff_pricing",subtitleFn:t=>{const e=t._val("tariff_provider")||"—",i=t._val("tariff_price_level")||"";return i?`${e} · ${i}`:e}},{id:"peak",icon:"mdi:flash-alert",color:"#ff9800",titleKey:"peak_load_management",subtitleFn:t=>{const e=t._valNum("consecutive_peak_15min").toFixed(1),i=t._valNum("monthly_consecutive_peak").toFixed(1);return`${t._t("peak")} ${e} kW · ${t._t("monthly_peak")} ${i} kW`}},{id:"system",icon:"mdi:cog-outline",color:"#96CAEE",titleKey:"system",subtitleFn:()=>""}],ue=["sensor.sem_charging_state","sensor.sem_daily_ev_energy","number.sem_daily_ev_target","select.sem_ev_charging_mode","switch.sem_night_charging","switch.sem_smart_night_charging","number.sem_ev_night_initial_current","number.sem_ev_minimum_current","number.sem_ev_stall_cooldown","number.sem_ev_phases","sensor.sem_surplus_active_devices","sensor.sem_surplus_total_devices","sensor.sem_surplus_allocated_w","sensor.sem_surplus_total_w","sensor.sem_surplus_distributable_w","sensor.sem_surplus_unallocated_w","number.sem_regulation_offset","sensor.sem_battery_soc","sensor.sem_battery_status","number.sem_battery_priority_soc","number.sem_battery_minimum_soc","number.sem_battery_resume_soc","sensor.sem_diag_battery_capacity","number.sem_hot_water_solar_target","number.sem_legionella_target_temp","number.sem_minimum_solar_power","number.sem_maximum_grid_import","sensor.sem_tariff_provider","sensor.sem_tariff_price_level","sensor.sem_tariff_current_import_rate","number.sem_cheap_price_threshold","number.sem_expensive_price_threshold","sensor.sem_consecutive_peak_15min","sensor.sem_monthly_consecutive_peak","sensor.sem_current_vs_peak_percentage","sensor.sem_load_management_status","sensor.sem_load_management_recommendation","sensor.sem_peak_margin","sensor.sem_available_load_reduction","sensor.sem_controllable_devices_count","switch.sem_observer_mode"];ft("sem-control-card",class extends mt{static get watchedEntities(){return ue}constructor(){super(),this._collapsed={ev:!1,surplus:!0,battery:!1,hotwater:!0,solar:!0,tariff:!1,peak:!0,system:!0}}setConfig(t){super.setConfig(t),this._prefix=t.entity_prefix||"sensor.sem_"}_val(t){const e=this._hass?.states[`${this._prefix}${t}`];return e&&"unavailable"!==e.state&&"unknown"!==e.state?e.state:""}_valNum(t,e=0){const i=this._hass?.states[`${this._prefix}${t}`];return i&&"unavailable"!==i.state&&"unknown"!==i.state&&parseFloat(i.state)||e}_numVal(t,e=0){const i=this._hass?.states[`number.sem_${t}`];return i&&"unavailable"!==i.state&&"unknown"!==i.state&&parseFloat(i.state)||e}_switchOn(t){return"on"===this._hass?.states[`switch.sem_${t}`]?.state}_toggleSection(t){this._collapsed={...this._collapsed,[t]:!this._collapsed[t]},this.requestUpdate()}_renderToggle(t,e,i){const s="on"===this._hass?.states[t]?.state;return H`
            <div class="toggle-row">
                <span class="toggle-label">${this._t(e)}</span>
                <div class="toggle-track ${s?"on":""}" @click=${()=>this._toggleSwitch(t)}>
                    <div class="toggle-thumb"></div>
                </div>
            </div>
        `}_renderStepper(t,e,i){const s=this._hass?.states[t];if(!s)return K;const r=this._frozenEntities[t],a=r?r.value:parseFloat(s.state)||0,o=parseFloat(s.attributes.step)||1,n=s.attributes.unit_of_measurement||"",l=o<1?1:0,c=a.toFixed(l)+(n?" "+n:"");return H`
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
                    <span class="stepper-value">${c}</span>
                    <button
                        class="stepper-plus" aria-label="Increase"
                        @click=${()=>this._stepNumber(t,1)}
                        @pointerdown=${()=>this._startHold(t,1)}
                        @pointerup=${()=>this._stopHold(t)}
                        @pointerleave=${()=>this._stopHold(t)}
                    >+</button>
                </div>
            </div>
        `}_renderSelect(t,e,i){const s=this._hass?.states[t];if(!s)return K;const r=this._frozenEntities[t],a=r?r.value:s.state,o=s.attributes.options||[];return H`
            <div class="ctrl-row">
                <span class="ctrl-label">${this._t(e)}</span>
                <select
                    class="sem-select"
                    .value=${a}
                    @change=${e=>this._selectOption(t,e.target.value)}
                >
                    ${o.map(t=>H`<option value="${t}" ?selected=${t===a}>${t}</option>`)}
                </select>
            </div>
        `}_renderEvSection(t){const e=this._hass?.states["number.sem_ev_minimum_current"],i=e&&parseFloat(e.state)>0,s=this._hass?.states["number.sem_ev_phases"],r=s&&parseFloat(s.state)>0;return H`
            ${this._renderSelect("select.sem_ev_charging_mode","ev_charging_mode",t)}
            <div class="toggle-group">
                ${this._renderToggle("switch.sem_night_charging","night_charging",t)}
                ${this._renderToggle("switch.sem_smart_night_charging","smart_night",t)}
            </div>
            ${this._renderStepper("number.sem_daily_ev_target","night_charge_target",t)}
            <div class="stepper-pair">
                ${this._renderStepper("number.sem_ev_night_initial_current","night_start_amps",t)}
                ${i?this._renderStepper("number.sem_ev_minimum_current","min_current",t):K}
            </div>
            <div class="stepper-pair">
                ${this._renderStepper("number.sem_ev_stall_cooldown","stall_cooldown",t)}
                ${r?this._renderStepper("number.sem_ev_phases","charger_phases",t):K}
            </div>
        `}_renderSurplusSection(t){const e=this._valNum("surplus_total_w").toFixed(0),i=this._valNum("surplus_distributable_w").toFixed(0),s=this._valNum("surplus_allocated_w").toFixed(0),r=this._valNum("surplus_unallocated_w").toFixed(0);return H`
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
        `}_renderBatterySection(t){const e=this._valNum("diag_battery_capacity"),i=e>0?e.toFixed(1)+" kWh":"—";return H`
            <div class="stepper-pair">
                ${this._renderStepper("number.sem_battery_priority_soc","priority_soc",t)}
                ${this._renderStepper("number.sem_battery_minimum_soc","minimum_soc",t)}
            </div>
            <div class="stepper-pair">
                ${this._renderStepper("number.sem_battery_resume_soc","resume_soc",t)}
                <div class="readonly-row">
                    <span class="ctrl-label">${this._t("capacity_kwh")}</span>
                    <span class="readonly-value">${i}</span>
                </div>
            </div>
        `}_renderHotWaterSection(t){return H`
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
        `}_renderSolarSection(t){return H`
            <div class="stepper-pair">
                ${this._renderStepper("number.sem_minimum_solar_power","min_solar",t)}
                ${this._renderStepper("number.sem_maximum_grid_import","max_grid_import",t)}
            </div>
        `}_renderTariffSection(t){const e=this._hass?.states["sensor.sem_tariff_current_import_rate"],i=e?e.state:"—",s=e?.attributes?.unit_of_measurement||"";return H`
            <div class="readonly-row tariff-rate-row">
                <ha-icon icon="mdi:flash" style="--mdc-icon-size:18px;color:#ff9800"></ha-icon>
                <span class="ctrl-label" style="flex:1">${this._t("current_electricity_price")}</span>
                <span class="readonly-value tariff-rate-value">${i} ${s}</span>
            </div>
            <div class="stepper-pair">
                ${this._renderStepper("number.sem_cheap_price_threshold","cheap_threshold",t)}
                ${this._renderStepper("number.sem_expensive_price_threshold","expensive_threshold",t)}
            </div>
        `}_renderPeakSection(t){const e=this._valNum("current_vs_peak_percentage"),i=e>90?"#f44336":e>70?"#ff9800":"#8DC892",s=this._valNum("controllable_devices_count").toFixed(0),r=this._valNum("available_load_reduction");return H`
            <div class="peak-hero">
                <span class="peak-pct" style="color:${i}">${e.toFixed(0)}%</span>
                <span class="peak-of-limit">${this._t("of_limit")}</span>
            </div>
            <div class="peak-detail">
                <span class="peak-status">${this._val("load_management_status")||"—"}</span>
                <span class="peak-sep">·</span>
                <span class="peak-rec">${this._val("load_management_recommendation")||""}</span>
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
        `}_renderSystemSection(t){return H`
            <div class="toggle-group">
                ${this._renderToggle("switch.sem_observer_mode","observer_mode",t)}
            </div>
        `}_renderSectionHeader(t,e){const i=this._collapsed[t.id],s=i?"rotate(-90deg)":"rotate(0deg)";return H`
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
        `}_renderSection(t,e,i){const s=this._collapsed[t.id];return H`
            <div class="section">
                ${this._renderSectionHeader(t,i)}
                <div class="section-content ${s?"":"expanded"}">
                    <div class="section-body">
                        ${e(i)}
                    </div>
                </div>
            </div>
        `}render(){if(!this._config)return K;const t=this._theme(),e=!1!==t.isDark,i=t.accent||"#42a5f5",s=this._switchOn("observer_mode"),r={ev:t=>this._renderEvSection(t),surplus:t=>this._renderSurplusSection(t),battery:t=>this._renderBatterySection(t),hotwater:t=>this._renderHotWaterSection(t),solar:t=>this._renderSolarSection(t),tariff:t=>this._renderTariffSection(t),peak:t=>this._renderPeakSection(t),system:t=>this._renderSystemSection(t)};return H`
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
                .section-title-text { font-size: 14px; font-weight: 600; white-space: nowrap; }
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
                .section-body { padding: 0 14px 14px; }

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

                /* ── Select ── */
                .ctrl-row {
                    display: flex; align-items: center; justify-content: space-between;
                    padding: 8px 0;
                    border-bottom: 1px solid ${t.surfaceBorder};
                    margin-bottom: 4px;
                }
                .ctrl-label { font-size: 13px; font-weight: 500; }
                .sem-select {
                    background: ${t.surface};
                    border: 1px solid ${t.surfaceBorder};
                    border-radius: 8px;
                    color: var(--primary-text-color, ${t.text});
                    padding: 6px 10px;
                    font-size: 13px;
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
                    font-size: 13px; font-weight: 500;
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
                    font-size: 13px; font-weight: 600;
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
                    font-size: 13px; font-weight: 600;
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
                ${_e.map(e=>this._renderSection(e,r[e.id],t))}
            </div>
        `}getCardSize(){return 12}static getStubConfig(){return{entity_prefix:"sensor.sem_"}}},{type:"custom:sem-control-card",name:"SEM Control Card",description:"Consolidated control panel for Solar Energy Management",preview:!1}),console.info("%c SEM Cards %c Lit Bundle ","color: #4db6ac; font-weight: bold; background: #1e232d; padding: 2px 6px; border-radius: 4px 0 0 4px;","color: #ff9800; background: #1e232d; padding: 2px 6px; border-radius: 0 4px 4px 0;");
