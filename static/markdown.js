/* Small, DOM-only Markdown renderer. Raw HTML is always text, never innerHTML.
   No CDN/scripts, images, embedded HTML or javascript: links from model output. */
window.renderMarkdown = function renderMarkdown(text) {
  const root = document.createElement('div');
  function inline(target, source) {
    const pattern = /(`[^`\n]+`|\*\*[^*\n]+\*\*|\[[^\]\n]+\]\(https?:\/\/[^\s)]+\))/g;
    let last = 0;
    for (const match of source.matchAll(pattern)) {
      target.append(document.createTextNode(source.slice(last, match.index)));
      const token = match[0];
      let element;
      if (token.startsWith('`')) {
        element = document.createElement('code'); element.textContent = token.slice(1, -1);
      } else if (token.startsWith('**')) {
        element = document.createElement('strong'); element.textContent = token.slice(2, -2);
      } else {
        const split = token.indexOf('](');
        element = document.createElement('a'); element.textContent = token.slice(1, split);
        element.href = token.slice(split + 2, -1); element.target = '_blank'; element.rel = 'noopener noreferrer';
      }
      target.append(element); last = match.index + token.length;
    }
    target.append(document.createTextNode(source.slice(last)));
  }
  const lines = text.replace(/\r\n/g, '\n').split('\n');
  let i = 0;
  while (i < lines.length) {
    if (lines[i].trimStart().startsWith('```')) {
      const lang = lines[i].trim().slice(3).trim(); i++;
      const contents = [];
      while (i < lines.length && !lines[i].trimStart().startsWith('```')) contents.push(lines[i++]);
      if (i < lines.length) i++;
      const block = document.createElement('div'); block.className = 'code-block';
      const header = document.createElement('div'); header.className = 'code-header';
      const name = document.createElement('span'); name.textContent = lang || 'code';
      const copy = document.createElement('button'); copy.type = 'button'; copy.className = 'copy-code';
      copy.textContent = 'Sao chép';
      copy.addEventListener('click', async () => {
        try { await navigator.clipboard.writeText(contents.join('\n')); copy.textContent = 'Đã sao chép ✓'; }
        catch { copy.textContent = 'Không thể sao chép'; }
        setTimeout(() => { copy.textContent = 'Sao chép'; }, 1600);
      });
      header.append(name, copy);
      const pre = document.createElement('pre'); const code = document.createElement('code');
      code.textContent = contents.join('\n'); pre.append(code); block.append(header, pre); root.append(block);
    } else if (!lines[i].trim()) { i++; }
    else if (/^#{1,6}\s/.test(lines[i])) {
      const count = lines[i].match(/^#+/)[0].length;
      const heading = document.createElement(`h${Math.min(count + 1, 4)}`);
      inline(heading, lines[i++].replace(/^#+\s*/, '')); root.append(heading);
    } else if (/^\s*([-*]|\d+\.)\s/.test(lines[i])) {
      const list = document.createElement(/^\s*\d+\./.test(lines[i]) ? 'ol' : 'ul');
      while (i < lines.length && /^\s*([-*]|\d+\.)\s/.test(lines[i])) {
        const item = document.createElement('li');
        inline(item, lines[i++].replace(/^\s*([-*]|\d+\.)\s+/, '')); list.append(item);
      }
      root.append(list);
    } else if (lines[i].includes('|') && i + 1 < lines.length && /^\s*\|?[\s:|\-]+\|\s*$/.test(lines[i + 1])) {
      const wrap = document.createElement('div'); wrap.className = 'markdown-table';
      const table = document.createElement('table'); let header = true;
      while (i < lines.length && lines[i].includes('|')) {
        const line = lines[i++];
        if (/^\s*\|?[\s:|\-]+\|\s*$/.test(line)) continue;
        const row = document.createElement('tr');
        for (const value of line.replace(/^\s*\||\|\s*$/g, '').split('|')) {
          const cell = document.createElement(header ? 'th' : 'td'); inline(cell, value.trim()); row.append(cell);
        }
        table.append(row); header = false;
      }
      wrap.append(table); root.append(wrap);
    } else {
      const paragraph = document.createElement('p');
      inline(paragraph, lines[i++]); root.append(paragraph);
    }
  }
  return root;
};
