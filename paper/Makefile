TEX := paper

.PHONY: all clean

all: $(TEX).pdf

$(TEX).pdf: $(TEX).tex $(TEX).bib wod_alpasim_2026.sty wodalpasimabbrvnat.bst
	pdflatex $(TEX)
	bibtex $(TEX)
	pdflatex $(TEX)
	pdflatex $(TEX)

clean:
	rm -f $(TEX).aux $(TEX).bbl $(TEX).blg $(TEX).log $(TEX).out $(TEX).synctex.gz $(TEX).toc
