(function () {
    window.ColorManager = {
        palette: [
            '#7FA38D',
            '#A37A87',
            '#BEAA7E',
            '#7E91BE',
            '#A89274',
            '#8F859A',
            '#C49B76',
            '#8B9B97',
            '#9C8E7D',
        ],
        assignedColors: new Map(),
        goldenAngle: 137.508,
        lastGeneratedHue: 0,

        init() {
            try {
                const savedMap = localStorage.getItem('aimanager_graph_colors');
                if (savedMap) this.assignedColors = new Map(JSON.parse(savedMap));

                const savedHue = localStorage.getItem('aimanager_last_hue');
                if (savedHue) this.lastGeneratedHue = parseFloat(savedHue);
                else this.lastGeneratedHue = Math.random() * 360;
            } catch (error) {
                console.warn('Could not load color state from LocalStorage', error);
                this.lastGeneratedHue = Math.random() * 360;
            }
        },

        saveState() {
            try {
                localStorage.setItem('aimanager_graph_colors', JSON.stringify([...this.assignedColors]));
                localStorage.setItem('aimanager_last_hue', this.lastGeneratedHue.toString());
            } catch (error) {
                console.warn('Could not save color state to LocalStorage', error);
            }
        },

        getColor(label) {
            if (!label) return '#99958E';

            const key = label.toLowerCase().trim();
            if (this.assignedColors.has(key)) {
                return this.assignedColors.get(key);
            }

            if (this.assignedColors.size < this.palette.length) {
                const color = this.palette[this.assignedColors.size];
                this.assignedColors.set(key, color);
                this.saveState();
                return color;
            }

            this.lastGeneratedHue = (this.lastGeneratedHue + this.goldenAngle) % 360;
            const generatedColor = `hsl(${Math.round(this.lastGeneratedHue)}, 30%, 55%)`;
            this.assignedColors.set(key, generatedColor);
            this.saveState();
            return generatedColor;
        },
    };

    window.ColorManager.init();
})();
