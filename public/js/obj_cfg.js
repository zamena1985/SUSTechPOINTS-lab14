// size is the dimension of the object in x/y/z axis, with unit meter.

class ObjectCategory
{


    obj_type_map = {
        Pedestrian:     {color: '#ff0000',  size:[0.4, 0.5, 1.7], attr:["umbrella", "sitting", "squating", "bending over", "luggage"]},
        Car:            {color: '#ff8800',  size:[4.5, 1.8, 1.5], attr:["door open", "trunk open"]},
        Truck:          {color: '#ffff00',  size:[10., 2.8, 3]},
        Trailer:        {color: '#88ff00',  size:[10., 2.8, 3]},
        Pipes:          {color: '#00ffff',  size:[10., 2.8, 3]},
        Dust:           {color: '#00aaff',  size:[10., 2.8, 3]},
        Infrastructure: {color: '#9d00ff',  size:[10., 2.8, 3]},
        Unknown:        {color: '#008888',  size:[4.5, 1.8, 1.5]},
        ego_truck:       {color: '#b17901',  size:[4.5, 1.8, 1.5]},
        ego_trailer:       {color: '#368800',  size:[4.5, 1.8, 1.5]},
    };


    constructor(){
        
    }

    popularCategories = ["Pedestrian", "Car", "Van", "Truck", "Trailer", "Pipes", "Dust", "Infrastructure", "Unknown", "ego_truck", "ego_trailer"];

    guess_obj_type_by_dimension(scale){

        var max_score = 0;
        var max_name = 0;
        this.popularCategories.forEach(i=>{
            var o = this.obj_type_map[i];
            var scorex = o.size[0]/scale.x;
            var scorey = o.size[1]/scale.y;
            var scorez = o.size[2]/scale.z;

            if (scorex>1) scorex = 1/scorex;
            if (scorey>1) scorey = 1/scorey;
            if (scorez>1) scorez = 1/scorez;

            if (scorex + scorey + scorez > max_score){
                max_score = scorex + scorey + scorez;
                max_name = i;
            }
        });

        console.log("guess type", max_name);
        return max_name;
    }

    global_color_idx = 0;
    get_color_by_id(id){
        let idx = parseInt(id);

        if (!idx)
        {
            idx = this.global_color_idx;
            this.global_color_idx += 1;
        }

        idx %= 33;
        idx = idx*19 % 33;

        return {
            x: idx*8/256.0,
            y: 1- idx*8/256.0,
            z: (idx<16)?(idx*2*8/256.0):((32-idx)*2*8/256.0),
        };
    }

    get_color_by_category(category){
        let target_color_hex = parseInt("0x"+this.get_obj_cfg_by_type(category).color.slice(1));
        
        return {
            x: (target_color_hex/256/256)/255.0,
            y: (target_color_hex/256 % 256)/255.0,
            z: (target_color_hex % 256)/255.0,
        };
    }

    get_obj_cfg_by_type(name){
        if (this.obj_type_map[name]){
            return this.obj_type_map[name];
        }
        else{
            return this.obj_type_map["Unknown"];
        }
    }

    // name_array = []

    // build_name_array(){
    //     for (var n in this.obj_type_map){
    //         name_array.push(n);
    //     }
    // }


    // get_next_obj_type_name(name){

    //     if (name_array.length == 0)    {
    //         build_name_array();
    //     }

    //     var idx = name_array.findIndex(function(n){return n==name;})
    //     idx+=1;
    //     idx %= name_array.length;

    //     return name_array[idx];
    // }

}


let globalObjectCategory = new ObjectCategory();

export {globalObjectCategory};