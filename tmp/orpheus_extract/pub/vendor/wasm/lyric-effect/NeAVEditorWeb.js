if (!window.WasmModule) window.WasmModule = {};
if (!window.WasmModule.LyricEffect) window.WasmModule.LyricEffect = {};
if (!window.WasmModule.LyricEffect.Utils)
  window.WasmModule.LyricEffect.Utils = {};

const g_NeAVEditor_BorderScale = 0.01;
const g_textMetrics = {};
const getTextMetrics = (fontFamily, fontSize) => {
  const metricsKey = `${fontFamily} ${fontSize}`;
  if (typeof g_textMetrics[metricsKey] === "undefined") {
    const container = document.createElement("div");
    const img = document.createElement("img");
    const span = document.createElement("span");
    const body = document.body;
    container.style.visibility = "hidden";
    container.style.fontFamily = fontFamily;
    container.style.fontSize = fontSize + "px";
    container.style.margin = "0";
    container.style.padding = "0";
    container.style.whiteSpace = "nowrap";
    body.appendChild(container);

    img.src =
      "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7";
    img.width = 1;
    img.height = 1;

    img.style.margin = "0";
    img.style.padding = "0";
    img.style.verticalAlign = "baseline";

    span.style.fontFamily = fontFamily;
    span.style.fontSize = fontSize;
    span.style.margin = "0";
    span.style.padding = "0";

    span.appendChild(document.createTextNode("Hg"));
    container.appendChild(span);
    container.appendChild(img);
    const baseline = img.offsetTop - span.offsetTop + 2;
    const height = span.offsetHeight;

    container.removeChild(span);
    container.appendChild(document.createTextNode("Hg"));

    container.style.lineHeight = "normal";
    img.style.verticalAlign = "super";

    const middle = img.offsetTop - container.offsetTop + 2;
    body.removeChild(container);
    let result = {};
    result.baseline = baseline;
    result.middle = middle;
    result.height = height;
    g_textMetrics[metricsKey] = result;
    return result;
  }
  return g_textMetrics[metricsKey];
};

const splitWords = (text) => {
  let words = [].concat.apply(
    [],
    text
      .split(/([a-zA-Z0-9]+)/g)
      .map((x) =>
        x.trim() != "" && !x.match(/([a-zA-Z0-9]+)/g) ? x.split("") : [x]
      )
  );
  if (words.length > 0 && words[0].length == 0) {
    words.splice(0, 1);
  }
  for (let n = 0; n < words.length;) {
    let curWord = words[n]
    if(curWord.length == 1 && curWord.match(/[\uD800-\uDBFF\uDC00-\uDFFF]/) && n < words.length-1){
      words[n] = words[n] + words[n+1];
      words.splice(n+1, 1);
      n++;
    }
    else{
      n++;
    }
  }
  return words;
};

const isContainChinese = (text) => {
  return !!text?.match(/[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]+/);
};

const measureTextInl = (ctx, text) => {
  return ctx.measureText(text).width;
};

const processEndEllipsis = (ctx, width, lineCurText, ellipsisWidth) => {
  do {
    if (measureTextInl(ctx, lineCurText) + ellipsisWidth <= width) {
      break;
    }
    lineCurText = lineCurText.substring(0, lineCurText.length - 1);
  } while (lineCurText.length > 0);
  return lineCurText + "...";
};

const parseRealLine = (
  ctx,
  width,
  height,
  lines,
  lineHeight,
  curlineSpace,
  ellipsisWidth
) => {
  let newLines = [];
  let curLineIdx = 0;
          
  for (let i = 0; i < lines.length; i++) {
    let lineText = lines[i];
    let words = splitWords(lineText);
    let lineWidth = 0;
    let lineCurText = "";
    let curY = 0;
    for (let n = 0; n < words.length; n++) {
      let word = words[n];
      let testLine = lineCurText + word;
      let metricsWidth = measureTextInl(ctx, testLine);
      if (metricsWidth <= width) {
        if (n == words.length - 1) {
          curY = (curLineIdx + 1) * lineHeight + curLineIdx * curlineSpace;
          if (
            curY + lineHeight + curlineSpace > height &&
            i < lines.length - 1
          ) {
            newLines.push(
              processEndEllipsis(ctx, width, testLine, ellipsisWidth)
            );
            return newLines;
          }
          newLines.push(testLine);
          curLineIdx++;
        } else {
          lineCurText = testLine;
        }
      } else {
        if (lineCurText == "" || word == ""){
          if(testLine.length > 0){
            lineCurText = testLine;
            word = "";
            do {
              if (measureTextInl(ctx, lineCurText) <= width) {
                break;
              }
              word = lineCurText.substring(lineCurText.length - 1, lineCurText.length)+word;
              lineCurText = lineCurText.substring(0, lineCurText.length - 1)
            } while (lineCurText.length > 0);
          }
          if(lineCurText.length > 0){
            curY = (curLineIdx + 1) * lineHeight + curLineIdx * curlineSpace;
            if (curY + lineHeight + curlineSpace > height) {
              newLines.push(
                processEndEllipsis(ctx, width, lineCurText, ellipsisWidth)
              );
              return newLines;
            }
            newLines.push(lineCurText);
            curLineIdx++;
            if (n == words.length - 1) {
              curY = (curLineIdx + 1) * lineHeight + curLineIdx * curlineSpace;
              if (
                curY + lineHeight + curlineSpace > height &&
                i < lines.length - 1
              ) {
                newLines.push(processEndEllipsis(ctx, width, word, ellipsisWidth));
                return newLines;
              }
              newLines.push(word);
              curLineIdx++;
            } else {
              lineCurText = word;
            }
          }
        }
        else{
          curY = (curLineIdx + 1) * lineHeight + curLineIdx * curlineSpace;
          if (curY + lineHeight + curlineSpace > height) {
            newLines.push(
              processEndEllipsis(ctx, width, lineCurText, ellipsisWidth)
            );
            return newLines;
          }
          newLines.push(lineCurText);
          curLineIdx++;
          if (n == words.length - 1) {
            curY = (curLineIdx + 1) * lineHeight + curLineIdx * curlineSpace;
            if (
              curY + lineHeight + curlineSpace > height &&
              i < lines.length - 1
            ) {
              newLines.push(processEndEllipsis(ctx, width, word, ellipsisWidth));
              return newLines;
            }
            newLines.push(word);
            curLineIdx++;
          } else {
            lineCurText = word;
          }
        }
      }
    }
  }
  return newLines;
};

const checkStringBlank = (text, flag) => {
  if (flag == 0) {
    for (let i = 0; i < text.length; i++) {
      if (text[i] !== " ") return i;
    }
  } else if (flag == 2) {
    for (let i = 0; i < text.length; i++) {
      if (text[text.length - 1 - i] !== " ") return i;
    }
  } else {
    let frontBlank = 0;
    for (let i = 0; i < text.length; i++) {
      if (text[i] !== " ") {
        frontBlank = i;
        break;
      }
    }
    let endBlank = 0;
    for (let i = 0; i < text.length; i++) {
      if (text[text.length - 1 - i] !== " ") {
        endBlank = i;
        break;
      }
    }
    return frontBlank - endBlank;
  }
  return 0;
};

const NeAVEditor_ColorConvert = (jstrColor) => {
  if(jstrColor.length == 8){
    let jsR = parseInt(jstrColor.substr(2, 2), 16);
    let jsG = parseInt(jstrColor.substr(4, 2), 16);
    let jsB = parseInt(jstrColor.substr(6, 2), 16);
    let jsA = parseInt(jstrColor.substr(0, 2), 16)/255.0;
    let colorStyle =
    "rgba(" + jsR + ", " + jsG + ", " + jsB + ", " + jsA.toFixed(2) + ")";
    return { ColorStyle: colorStyle,
             ColorAlpha: jsA};
  }
  else{
    let jsR = parseInt(jstrColor.substr(0, 2), 16);
    let jsG = parseInt(jstrColor.substr(2, 2), 16);
    let jsB = parseInt(jstrColor.substr(4, 2), 16);
    let colorStyle =
    "rgba(" + jsR + ", " + jsG + ", " + jsB + ", " + 0.0 + ")";
    return { ColorStyle: colorStyle,
             ColorAlpha: 0.0};
  }
};

window.WasmModule.LyricEffect.Utils.NeAVEditor_HslToRgb = (h, s, l) => {
  h /= 360;
  s /= 100;
  l /= 100;

  const c = (1 - Math.abs(2 * l - 1)) * s;
  const x = c * (1 - Math.abs((h / 60) % 2 - 1));
  const m = l - c / 2;

  let r = 0;
  let g = 0;
  let b = 0;

  if (h >= 0 && h < 60) {
    r = c;
    g = x;
  } else if (h >= 60 && h < 120) {
    r = x;
    g = c;
  } else if (h >= 120 && h < 180) {
    g = c;
    b = x;
  } else if (h >= 180 && h < 240) {
    g = x;
    b = c;
  } else if (h >= 240 && h < 300) {
    r = x;
    b = c;
  } else {
    r = c;
    b = x;
  }

  r += m;
  g += m;
  b += m;

  r *= 255;
  g *= 255;
  b *= 255;

  return { R: r, G: g, B: b };
};

window.WasmModule.LyricEffect.Utils.NeAVEditor_RgbToHsl = (r, g, b) => {
  r /= 255;
  g /= 255;
  b /= 255;

  const cmax = Math.max(r, g, b);
  const cmin = Math.min(r, g, b);
  const delta = cmax - cmin;

  let h = 0;
  let s = 0;
  let l = (cmax + cmin) / 2;

  if (delta !== 0) {
    if (l < 0.5) {
      s = delta / (cmax + cmin);
    } else {
      s = delta / (2 - cmax - cmin);
    }

    if (cmax === r) {
      h = (g - b) / delta;
    } else if (cmax === g) {
      h = 2 + (b - r) / delta;
    } else {
      h = 4 + (r - g) / delta;
    }

    h *= 60;
    if (h < 0) {
      h += 360;
    }
  }

  return { H: h, S: s, L: l };
};

window.WasmModule.LyricEffect.Utils.NeAVEditor_NeedGrayColor = (h, s, l) => {
  if(s < 0.05 || l < 0.05 || l > 0.98
    || (s < 0.15 && l < 0.1) || (s < 0.1 && l> 0.9)){
      return true;
  }
  return false;
};

const NeAVEditor_MixFloat = (a, b, ratio) =>{
  return a + (b - a) * ratio;
}

window.WasmModule.LyricEffect.Utils.NeAVEditor_MixColor = ({ R: R1, G: G1, B: B1 }, { R: R2, G: G2, B: B2 }, ratio) => {
  return { R: NeAVEditor_MixFloat(R1, R2, ratio), G: NeAVEditor_MixFloat(G1, G2, ratio), B: NeAVEditor_MixFloat(B1, B2, ratio) };
};

window.WasmModule.LyricEffect.Utils.NeAVEditor_StyleColor = ({ R: r, G: g, B: b }) => {
  return `rgb(${Math.round(r*255)}, ${Math.round(g*255)}, ${Math.round(b*255)})`;;
};

window.WasmModule.LyricEffect.Utils.NeAVEditor_drawString = (
  jsText,
  jsFontName,
  jsFontPath,
  jsAlign,
  jsVAlign,
  jsVertical,
  jsUnderline,
  jsLetterSpace,
  jsLinespace,
  jswhsize,
  jsColorStr,
  jsBorderColorStr,
  jsBorderWidth,
  jsBold,
  jsRange,
  jsRangeColorStr,
  jsRangeBorderColorStr,
  jsRangeBorderWidth,
  jsPadding,
  jsPixelData
) => {
  const loadFontFile = window.WasmModule.LyricEffect.Utils.loadFontFile;
  let whsizeInfo = jswhsize.split("/");
  let jsWidth = parseInt(whsizeInfo[0], 10);
  let jsHeight = parseInt(whsizeInfo[1], 10);
  let jsFontSize = parseInt(whsizeInfo[2], 10);
  let jsFontSizeNum = parseInt(whsizeInfo[3], 10);
  let jsFontSizeArray = [];
  for(let i = 0; i < jsFontSizeNum; i++){
    jsFontSizeArray.push(parseInt(whsizeInfo[4+i], 10));
  }
  let fontColorS = NeAVEditor_ColorConvert(jsColorStr);
  let jsA = fontColorS.ColorAlpha;
  let colorStyle = fontColorS.ColorStyle;
  let borderColorS = NeAVEditor_ColorConvert(jsBorderColorStr);
  let jsBorderA = borderColorS.ColorAlpha;
  let borderStyle = borderColorS.ColorStyle;
  let rangeColorStyle = "";
  let rangeBorderStyle = "";
  let jsRaA = 0.0;
  let jsRaBA = 0.0;
  if(jsRange != 0){
    let rangeColorS = NeAVEditor_ColorConvert(jsRangeColorStr);
    jsRaA = rangeColorS.ColorAlpha;
    rangeColorStyle = rangeColorS.ColorStyle;
    let rangeBorderColorS = NeAVEditor_ColorConvert(jsRangeBorderColorStr);
    jsRaBA = rangeBorderColorS.ColorAlpha;
    rangeBorderStyle = rangeBorderColorS.ColorStyle;
  }
  const fontFamily = jsFontPath.length > 0 ? `'${jsFontName}'` : "sans-serif";
  let text = jsText.replace("\r", "");
  if (!isContainChinese(text)) {
    jsLetterSpace = jsLetterSpace * 0.25;
  }
  if (jsFontPath.length > 0) loadFontFile(jsFontName, jsFontPath);
  let canvas = document.getElementById("canvasRaw");
  canvas.width = jsWidth;
  canvas.height = jsHeight;
  let ctx = canvas.getContext("2d");
  ctx.letterSpacing = jsLetterSpace + "px";
  ctx.fillStyle = "rgba(0,0,0,0)";
  ctx.fillRect(0, 0, jsWidth, jsHeight);
  ctx.fillStyle = colorStyle;
  let paddingW = jsPadding * 2.0;
  ctx.lineJoin = window.chrome ? "miter" : "round";
  ctx.strokeStyle = borderStyle;
  let lines = text.split("\n");
  if(jsFontSize < 0){
    for (let i = 0; i < jsFontSizeArray.length; i++) {
      jsFontSize = jsFontSizeArray[i];
      let tmpcurBorderWidth = Math.abs(jsBorderWidth) * jsFontSize * g_NeAVEditor_BorderScale;
      ctx.lineWidth = tmpcurBorderWidth;
      ctx.font =
        jsBold >= 1
          ? `bold ${jsFontSize}px ${fontFamily}`
          : `normal ${jsFontSize}px ${fontFamily}`;
      var tmpjsTextMetrics = getTextMetrics(fontFamily, jsFontSize);
      let tmpellipsisWidth = measureTextInl(ctx, "...");
      let tmplineHeight = tmpjsTextMetrics.height;
      let tmpcurlineSpace = jsFontSize * (0.06 + jsLinespace - 1.0);
      let tmpnewLines = parseRealLine(
        ctx,
        jsWidth - tmpcurBorderWidth - paddingW,
        4096,
        lines,
        tmplineHeight,
        tmpcurlineSpace,
        tmpellipsisWidth
      );
      let tmptotalHeight = tmpnewLines.length * tmplineHeight + (tmpnewLines.length - 1) * tmpcurlineSpace;
      if(tmptotalHeight <= jsHeight){
        break;
      }
    }
  }
  let curBorderWidth = Math.abs(jsBorderWidth) * jsFontSize * g_NeAVEditor_BorderScale;
  let halfBorderWidth = curBorderWidth * 0.5;
  ctx.lineWidth = curBorderWidth;
  ctx.font =
    jsBold >= 1
      ? `bold ${jsFontSize}px ${fontFamily}`
      : `normal ${jsFontSize}px ${fontFamily}`;
  var jsTextMetrics = getTextMetrics(fontFamily, jsFontSize);
  let ellipsisWidth = measureTextInl(ctx, "...");
  let blankWidth = measureTextInl(ctx, " ");
  let lineHeight = jsTextMetrics.height;
  let curlineSpace = jsFontSize * (0.06 + jsLinespace - 1.0);
  let newLines = parseRealLine(
    ctx,
    jsWidth - curBorderWidth - paddingW,
    jsHeight,
    lines,
    lineHeight,
    curlineSpace,
    ellipsisWidth
  );
  let totalHeight =
    newLines.length * lineHeight + (newLines.length - 1) * curlineSpace;
  let yOffset = 0.0;
  if (jsVAlign == 1) {
    yOffset = (jsHeight - totalHeight) * 0.5;
  } else if (jsVAlign == 2) {
    yOffset = (jsHeight - totalHeight) * 1.0;
    yOffset = yOffset - halfBorderWidth - jsPadding;
  } else {
    yOffset = yOffset + halfBorderWidth + jsPadding;
  }

  ctx.textAlign = "left";
  let jsLayout = [0.0];
  let totalChar = 0.0;
  let baseOffset = jsTextMetrics.height - jsTextMetrics.baseline;
  if(jsRange != 0){
    for (let i = 0; i < newLines.length; i++) {
      let curLine = newLines[i];
      let lineWidth = measureTextInl(ctx, curLine);
      let xOffset = 0.0;
      if (jsAlign == 1) {
        xOffset = (jsWidth - lineWidth) * 0.5;
        xOffset = xOffset - checkStringBlank(curLine, 1) * blankWidth * 0.5;
      } else if (jsAlign == 2) {
        xOffset = (jsWidth - lineWidth) * 1.0;
        xOffset = xOffset - halfBorderWidth - jsPadding;
        xOffset = xOffset + checkStringBlank(curLine, 2) * blankWidth;
      } else {
        xOffset = xOffset + halfBorderWidth + jsPadding;
        xOffset = xOffset - checkStringBlank(curLine, 0) * blankWidth;
      }
      let curYOffset =
        yOffset + (i + 1) * lineHeight + i * curlineSpace - baseOffset;
      if(jsRange > 0 && i == 0){
        ctx.fillStyle = rangeColorStyle;
        ctx.strokeStyle = rangeBorderStyle;
        ctx.lineWidth =  Math.abs(jsRangeBorderWidth) * jsFontSize * g_NeAVEditor_BorderScale;
        let startX = 0;
        let splitX = 0;
        for (let c = 0; c < curLine.length; c++) {
          let curSubLen = measureTextInl(ctx, curLine.substring(0, c + 1));
          jsLayout.push(startX + xOffset);
          jsLayout.push(curYOffset + baseOffset - lineHeight);
          jsLayout.push(curSubLen - startX);
          jsLayout.push(lineHeight);
          totalChar += 1.0;
          startX = curSubLen;
          if(c == jsRange-1){
            splitX = startX;
          }
        }
        let rangLen = Math.min(jsRange, curLine.length);
        let startLine = curLine.substr(0, rangLen);
        if (ctx.lineWidth > 0.0 && jsRangeBorderWidth < 0.0) {
          ctx.strokeText(startLine, xOffset, curYOffset);
        }
        if (jsRaA > 0.0) {
          ctx.fillText(startLine, xOffset, curYOffset);
        }
        if (ctx.lineWidth > 0.0 && jsRangeBorderWidth > 0.0) {
          ctx.strokeText(startLine, xOffset, curYOffset);
        }
        if(curLine.length > jsRange){
          ctx.fillStyle = colorStyle;
          ctx.strokeStyle = borderStyle;
          ctx.lineWidth = curBorderWidth;
          let endLine = curLine.substr(rangLen, curLine.length-jsRange);
          if (curBorderWidth > 0.0 && jsBorderWidth < 0.0) {
            ctx.strokeText(endLine, xOffset+splitX, curYOffset);
          }
          if (jsA > 0.0) {
            ctx.fillText(endLine, xOffset+splitX, curYOffset);
          }
          if (curBorderWidth > 0.0 && jsBorderWidth > 0.0) {
            ctx.strokeText(endLine, xOffset+splitX, curYOffset);
          }
        }
      }
      else if(jsRange < 0 && i == newLines.length-1){
        let startX = 0;
        let splitX = 0;
        let rangeValue = -jsRange;

        for (let c = 0; c < curLine.length; c++) {
          let curSubLen = measureTextInl(ctx, curLine.substring(0, c + 1));
          jsLayout.push(startX + xOffset);
          jsLayout.push(curYOffset + baseOffset - lineHeight);
          jsLayout.push(curSubLen - startX);
          jsLayout.push(lineHeight);
          totalChar += 1.0;
          startX = curSubLen;
          if(c == curLine.length-rangeValue-1){
            splitX = startX;
          }
        }
        let rangLen = Math.min(rangeValue, curLine.length);
        if(curLine.length > rangeValue){
          ctx.fillStyle = colorStyle;
          ctx.strokeStyle = borderStyle;
          ctx.lineWidth = curBorderWidth;
          let rangLen = Math.min(rangeValue, curLine.length);
          let startLine = curLine.substr(0, curLine.length-rangLen);
          let endLine = curLine.substr(curLine.length-rangLen, rangLen);
          if (curBorderWidth > 0.0 && jsBorderWidth < 0.0) {
            ctx.strokeText(startLine, xOffset, curYOffset);
          }
          if (jsA > 0.0) {
            ctx.fillText(startLine, xOffset, curYOffset);
          }
          if (curBorderWidth > 0.0 && jsBorderWidth > 0.0) {
            ctx.strokeText(startLine, xOffset, curYOffset);
          }
          ctx.fillStyle = rangeColorStyle;
          ctx.strokeStyle = rangeBorderStyle;
          ctx.lineWidth =  Math.abs(jsRangeBorderWidth) * jsFontSize * g_NeAVEditor_BorderScale;
          if (ctx.lineWidth > 0.0 && jsRangeBorderWidth < 0.0) {
            ctx.strokeText(endLine, splitX+xOffset, curYOffset);
          }
          if (jsRaA > 0.0) {
            ctx.fillText(endLine, splitX+xOffset, curYOffset);
          }
          if (ctx.lineWidth > 0.0 && jsRangeBorderWidth > 0.0) {
            ctx.strokeText(endLine, splitX+xOffset, curYOffset);
          }
        }
        else{
          ctx.fillStyle = rangeColorStyle;
          ctx.strokeStyle = rangeBorderStyle;
          ctx.lineWidth =  Math.abs(jsRangeBorderWidth) * jsFontSize * g_NeAVEditor_BorderScale;
          if (ctx.lineWidth > 0.0 && jsRangeBorderWidth < 0.0) {
            ctx.strokeText(curLine, xOffset, curYOffset);
          }
          if (jsRaA > 0.0) {
            ctx.fillText(curLine, xOffset, curYOffset);
          }
          if (ctx.lineWidth > 0.0 && jsRangeBorderWidth > 0.0) {
            ctx.strokeText(curLine, xOffset, curYOffset);
          }
        }
      }
      else{
        ctx.fillStyle = colorStyle;
        ctx.strokeStyle = borderStyle;
        ctx.lineWidth = curBorderWidth;
        let startX = 0;
        for (let c = 0; c < curLine.length; c++) {
          let curSubLen = measureTextInl(ctx, curLine.substring(0, c + 1));
          jsLayout.push(startX + xOffset);
          jsLayout.push(curYOffset + baseOffset - lineHeight);
          jsLayout.push(curSubLen - startX);
          jsLayout.push(lineHeight);
          totalChar += 1.0;
          startX = curSubLen;
        }
        if (curBorderWidth > 0.0 && jsBorderWidth < 0.0) {
          ctx.strokeText(curLine, xOffset, curYOffset);
        }
        if (jsA > 0.0) {
          ctx.fillText(curLine, xOffset, curYOffset);
        }
        if (curBorderWidth > 0.0 && jsBorderWidth > 0.0) {
          ctx.strokeText(curLine, xOffset, curYOffset);
        }
      }
    }
  }
  else{
    for (let i = 0; i < newLines.length; i++) {
      let curLine = newLines[i];
      let lineWidth = measureTextInl(ctx, curLine);
      let xOffset = 0.0;
      if (jsAlign == 1) {
        xOffset = (jsWidth - lineWidth) * 0.5;
        xOffset = xOffset - checkStringBlank(curLine, 1) * blankWidth * 0.5;
      } else if (jsAlign == 2) {
        xOffset = (jsWidth - lineWidth) * 1.0;
        xOffset = xOffset - halfBorderWidth - jsPadding;
        xOffset = xOffset + checkStringBlank(curLine, 2) * blankWidth;
      } else {
        xOffset = xOffset + halfBorderWidth + jsPadding;
        xOffset = xOffset - checkStringBlank(curLine, 0) * blankWidth;
      }
      let curYOffset =
        yOffset + (i + 1) * lineHeight + i * curlineSpace - baseOffset;
      let startX = 0;
      for (let c = 0; c < curLine.length; c++) {
        let curSubLen = measureTextInl(ctx, curLine.substring(0, c + 1));
        jsLayout.push(startX + xOffset);
        jsLayout.push(curYOffset + baseOffset - lineHeight);
        jsLayout.push(curSubLen - startX);
        jsLayout.push(lineHeight);
        totalChar += 1.0;
        startX = curSubLen;
      }
      if (curBorderWidth > 0.0 && jsBorderWidth < 0.0) {
        ctx.strokeText(curLine, xOffset, curYOffset);
      }
      if (jsA > 0.0) {
        ctx.fillText(curLine, xOffset, curYOffset);
      }
      if (curBorderWidth > 0.0 && jsBorderWidth > 0.0) {
        ctx.strokeText(curLine, xOffset, curYOffset);
      }
    }
  }

  jsLayout[0] = totalChar;
  if (jsPixelData != null) {
    let imageData = ctx.getImageData(0, 0, jsWidth, jsHeight).data;
    window.WasmModule.LyricEffect.HEAPU8.set(imageData, jsPixelData);
  }

  let retLayout = window.WasmModule.LyricEffect._malloc(jsLayout.length * 4);
  window.WasmModule.LyricEffect.HEAPF32.set(jsLayout, retLayout >> 2);
  return retLayout;
};

window.WasmModule.LyricEffect.Utils.NeAVEditor_measureString = (
  jsText,
  jsFontName,
  jsFontPath,
  jsFontSize,
  jsLetterSpace,
  jsLinespace,
  jsWidth,
  jsBorderWidth,
  jsBold
) => {
  const loadFontFile = window.WasmModule.LyricEffect.Utils.loadFontFile;
  const fontFamily = jsFontPath.length > 0 ? `'${jsFontName}'` : "sans-serif";
  let text = jsText.replace("\r", "");
  if (!isContainChinese(text)) {
    jsLetterSpace = jsLetterSpace * 0.25;
  }
  if (jsFontPath.length > 0) loadFontFile(jsFontName, jsFontPath);
  var jsTextMetrics = getTextMetrics(fontFamily, jsFontSize);

  let canvas = document.getElementById("canvasRaw");
  let jsHeight = 4096;
  let ctx = canvas.getContext("2d");
  ctx.letterSpacing = jsLetterSpace + "px";
  let curBorderWidth = Math.abs(jsBorderWidth) * jsFontSize * g_NeAVEditor_BorderScale;
  let halfBorderWidth = curBorderWidth * 0.5;
  ctx.lineWidth = curBorderWidth;
  ctx.lineJoin = window.chrome ? "miter" : "round";
  ctx.font =
    jsBold >= 1
      ? `bold ${jsFontSize}px ${fontFamily}`
      : `normal ${jsFontSize}px ${fontFamily}`;
  let lines = text.split("\n");
  let ellipsisWidth = measureTextInl(ctx, "...");
  let blankWidth = measureTextInl(ctx, " ");
  let lineHeight = jsTextMetrics.height;
  let curlineSpace = jsFontSize * (0.06 + jsLinespace - 1.0);
  let newLines = parseRealLine(
    ctx,
    (jsWidth <= 0 ? 4000 : jsWidth) - curBorderWidth,
    jsHeight,
    lines,
    lineHeight,
    curlineSpace,
    ellipsisWidth
  );
  let totalHeight =
    newLines.length * lineHeight + (newLines.length - 1) * curlineSpace;
  let totalWidth = 0;
  if(jsWidth <= 0){
    for (let i = 0; i < newLines.length; i++) {
      let curLine = newLines[i];
      totalWidth = Math.max(totalWidth, measureTextInl(ctx, curLine));
    }
    totalWidth += curBorderWidth;
  }
  else{
    totalWidth = jsWidth;
  }
  let jsRetSize = [totalWidth, totalHeight];
  let retSize = window.WasmModule.LyricEffect._malloc(2 * 4);
  window.WasmModule.LyricEffect.HEAP32.set(jsRetSize, retSize >> 2);
  return retSize;
}

window.WasmModule.LyricEffect.Utils.NeAVEditor_layoutString = (
  jsText,
  jsFontName,
  jsFontPath,
  jsFontSize,
  jsLetterSpace,
  jsWidth,
  jsBorderWidth,
  jsBold
) => {
  const loadFontFile = window.WasmModule.LyricEffect.Utils.loadFontFile;
  loadFontFile(jsFontName, jsFontPath);
  const fontFamily = jsFontPath.length > 0 ? `'${jsFontName}'` : "sans-serif";
  let canvas = document.getElementById("canvasRaw");
  let ctx = canvas.getContext("2d");
  let text = jsText.replace("\r", "");
  if (!isContainChinese(text)) {
    jsLetterSpace = jsLetterSpace * 0.25;
  }
  let curBorderWidth = Math.abs(jsBorderWidth) * jsFontSize * g_NeAVEditor_BorderScale;
  // remove the border effect
  jsWidth = jsWidth - curBorderWidth;
  if (jsFontPath.length > 0) loadFontFile(jsFontName, jsFontPath);
  let lines = text.split("\n");
  ctx.font =
    jsBold >= 1
      ? `bold ${jsFontSize}px ${fontFamily}`
      : `normal ${jsFontSize}px ${fontFamily}`;
  ctx.letterSpacing = jsLetterSpace + "px";
  ctx.textAlign = "left";
  var jsTextMetrics = getTextMetrics(fontFamily, jsFontSize);
  let ellipsisWidth = measureTextInl(ctx, "...");
  let blankWidth = measureTextInl(ctx, " ");
  let jsHeight = 4096;
  let lineHeight = jsTextMetrics.height;
  let curlineSpace = jsFontSize * (0.06);
  let newLines = parseRealLine(
    ctx,
    jsWidth,
    jsHeight,
    lines,
    lineHeight,
    curlineSpace,
    ellipsisWidth
  );
  let jsLayout = [0];
  for (let i = 0; i < newLines.length; i++) {
    let curLine = newLines[i];
    jsLayout.push(curLine.length);
  }
  jsLayout[0] = jsLayout.length - 1;
  let retLayout = window.WasmModule.LyricEffect._malloc(jsLayout.length * 4);
  window.WasmModule.LyricEffect.HEAP32.set(jsLayout, retLayout >> 2);
  return retLayout;
};
window.WasmModule.LyricEffect.Utils.getSDKVersion = () => {
  return 33;
};
