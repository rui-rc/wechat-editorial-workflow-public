"""Small helpers for native Xiumi components in the existing browser session.

These operate on rendered editor controls. They do not fetch template payloads,
rewrite component models, or flatten a card into HTML.
"""
import html
import json
from pathlib import Path
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from same_session import snapshot


def select_component_anchor(driver, text):
    """Select the top-level component, with no text caret that could split it."""
    cell = driver.execute_script("""
    const cells=[...document.querySelectorAll('div[contenteditable="true"]')]
      .filter(e=>e.offsetWidth>0 && e.textContent===arguments[0]);
    if(cells.length!==1)throw Error('Anchor must identify exactly one text cell');
    const root=cells[0].closest('.tn-comp-top-level');
    if(!root || cells[0].closest('.tn-comp')!==root)
      throw Error('Nested text is not a top-level anchor; select the group in layout mode');
    cells[0].scrollIntoView({block:'center'});return cells[0];
    """, text)
    cell.click()
    WebDriverWait(driver,10,poll_frequency=.2).until(lambda d:d.execute_script(
        "return arguments[0].closest('.tn-comp-top-level').classList.contains('tn-on-editing')",cell))
    # A first click selects a component; a second click may enter its text.
    # Escape in selection mode would deselect the anchor entirely.
    if driver.execute_script('return document.activeElement.isContentEditable'):
        driver.switch_to.active_element.send_keys(Keys.ESCAPE)
    def selected(d):
        return d.execute_script("""
        const cells=[...document.querySelectorAll('div[contenteditable="true"]')]
          .filter(e=>e.offsetWidth>0 && e.textContent===arguments[0]);
        const chosen=[...document.querySelectorAll('.tn-page .tn-comp-top-level.tn-on-editing')];
        return !document.activeElement.isContentEditable && cells.length===1 &&
          chosen.length===1 && chosen[0]===cells[0].closest('.tn-comp-top-level');
        """, text)
    WebDriverWait(driver,10,poll_frequency=.2).until(selected)


def replace_native_text(driver, old, new, backup_path):
    """Replace one single-run text cell while preserving its rich-text wrapper.

Repeated text, multi-run formatting and embedded media require a narrower manual
selection. This deliberately refuses them before typing. Save/reopen separately.
    """
    if not old or not new or '\n' in new or '\r' in new:
        raise ValueError('One nonempty text cell is required')
    before = snapshot(driver)
    hits = [i for i,c in enumerate(before) if c['textContent']==old]
    if len(hits)!=1:
        raise ValueError('Text must identify exactly one native cell')
    index=hits[0]
    expected_html=before[index]['html']
    escaped=html.escape(old,quote=False)
    if expected_html.count(escaped)!=1:
        raise ValueError('Text spans multiple runs; use a scoped native selection')
    target=Path(backup_path)
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('x',encoding='utf-8') as stream:
        json.dump({'before':before,'cell_index':index,'old':old,'new':new},stream,ensure_ascii=False,indent=2)
    cell=driver.execute_script("""
    const cs=[...document.querySelectorAll('div[contenteditable="true"]')]
      .filter(e=>e.offsetWidth>0&&e.textContent===arguments[0]);
    if(cs.length!==1)throw Error('Native text cell changed');
    const c=cs[0],walk=document.createTreeWalker(c,NodeFilter.SHOW_TEXT);let nodes=[],n;
    while(n=walk.nextNode())if(n.textContent.trim())nodes.push(n);
    if(nodes.length!==1||nodes[0].textContent!==arguments[0]||c.querySelector('img,svg,video,audio,br'))
      throw Error('Cell is not one plain text run');
    c.scrollIntoView({block:'center'});return c;
    """, old)
    cell.click()
    selected=driver.execute_script("""
    const c=arguments[0],walk=document.createTreeWalker(c,NodeFilter.SHOW_TEXT);let n;
    while(n=walk.nextNode())if(n.textContent===arguments[1]){
      c.focus();const r=document.createRange();r.selectNodeContents(n);
      const s=getSelection();s.removeAllRanges();s.addRange(r);
      return document.activeElement===c && s.toString()===arguments[1];
    }return false;
    """,cell,old)
    if not selected:
        raise RuntimeError('Native text selection was not confirmed')
    driver._wf_save_uncertain=True
    driver.execute_cdp_cmd('Input.insertText',{'text':new})
    WebDriverWait(driver,10,poll_frequency=.2).until(
        lambda d: any(c['textContent']==new for c in snapshot(d)))
    after=snapshot(driver)
    expected=[c['html'] for c in before]
    expected[index]=expected_html.replace(escaped,html.escape(new,quote=False),1)
    if [c['html'] for c in after]!=expected:
        raise RuntimeError('Native edit changed formatting or another cell; inspect before saving')
    return {'cell_index':index,'expected_html':expected,'backup_path':str(target)}
